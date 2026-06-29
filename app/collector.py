"""Coleta e normalizacao dos concursos a partir do site Concursos no Brasil.

Fonte: https://concursosnobrasil.com
- Concursos abertos: uma pagina por estado em /concursos/<uf>/
- Concursos previstos: uma unica pagina nacional em /concursos/previstos/

Diferente da API antiga (que so devolvia orgao e numero de vagas), aqui cada
concurso vem com o LINK direto para a sua pagina, um titulo descritivo e a data
de publicacao. A coleta continua DEFENSIVA: cada linha da tabela e lida com
tolerancia e, se a estrutura mudar, o item e ignorado sem quebrar o resto.
"""

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
from io import BytesIO
from urllib.parse import urljoin

import httpx

from . import db

# Trava global: garante que apenas UMA coleta/enriquecimento rode por vez.
# Sem ela, a coleta do boot (que tambem le os editais, demorada) poderia
# colidir com a coleta horaria do agendador, duplicando trabalho e gravacoes.
_LOCK_COLETA = threading.Lock()

# Quantas vezes tentar baixar uma pagina antes de desistir, e a espera inicial
# entre as tentativas (dobrada a cada vez: backoff exponencial).
HTTP_TENTATIVAS = int(os.environ.get("HTTP_TENTATIVAS", "3"))
HTTP_BACKOFF = float(os.environ.get("HTTP_BACKOFF", "1.0"))

# Os 27 UFs do Brasil (26 estados mais o Distrito Federal).
UFS = [
    "ac", "al", "ap", "am", "ba", "ce", "df", "es", "go", "ma", "mt", "ms",
    "mg", "pa", "pb", "pr", "pe", "pi", "rj", "rn", "rs", "ro", "rr", "sc",
    "sp", "se", "to",
]

BASE_URL = "https://concursosnobrasil.com"

# User-Agent identificavel, mas em formato compativel com navegador para o site
# nao recusar a requisicao.
USER_AGENT = (
    "Mozilla/5.0 (compatible; RastreadorDeConcursos/2.0; "
    "+https://github.com/seu-usuario/rastreador-de-concursos)"
)

# Pausa entre as requisicoes para nao sobrecarregar a fonte.
PAUSA_SEGUNDOS = 0.5

# A pagina de previstos e nacional e tem milhares de itens (varios antigos).
# Por isso pegamos apenas os mais recentes. Configuravel por ambiente.
MAX_PREVISTOS = int(os.environ.get("MAX_PREVISTOS", "500"))

# Enriquecimento por detalhe (data de encerramento, link oficial e PDF do edital).
# Roda em lotes, fora da coleta principal, para nao deixar tudo lento.
LER_PDF = os.environ.get("LER_PDF", "1") not in ("0", "false", "False")
LOTE_DETALHES = int(os.environ.get("LOTE_DETALHES", "20"))
PAUSA_DETALHE = float(os.environ.get("PAUSA_DETALHE", "0.4"))
# Tamanho maximo de PDF a baixar e numero de paginas a ler.
PDF_MAX_BYTES = 8 * 1024 * 1024
PDF_MAX_PAGINAS = 15

# Meses por extenso para extrair as datas de inscricao do texto.
_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}
_RE_DATA_PT = re.compile(
    r"(\d{1,2})\s+de\s+"
    r"(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|"
    r"setembro|outubro|novembro|dezembro)"
    r"(?:\s+de\s+(\d{4}))?",
    re.I,
)

# Expressoes para varrer a tabela de concursos de forma tolerante.
_RE_LINHA = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_RE_ANCORA = re.compile(r"<a\s+([^>]*?)>(.*?)</a>", re.S)
_RE_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
# Os links de concurso sempre tem uma data no caminho: /AAAA/MM/DD/.
_RE_DATA = re.compile(r"/(20\d\d)/(\d\d)/(\d\d)/")


def _limpa(texto):
    # Remove tags HTML e normaliza os espacos.
    texto = re.sub(r"<[^>]+>", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _atributo(atributos, nome):
    # Le o valor de um atributo HTML (ex: href, title) de forma tolerante.
    m = re.search(nome + r'="([^"]*)"', atributos)
    return m.group(1) if m else ""


def _data_do_link(link):
    # Extrai a data de publicacao do caminho do link, em formato AAAA-MM-DD.
    m = _RE_DATA.search(link)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def _uf_do_link(link, uf_padrao):
    # O caminho costuma ser /concursos/<uf>/AAAA/MM/DD/...; se houver uma sigla
    # de estado valida ali, usamos ela. Senao, usamos a uf da pagina.
    try:
        partes = link.split("/concursos/")[-1].split("/")
    except Exception:
        return uf_padrao
    primeira = partes[0] if partes else ""
    if len(primeira) == 2 and primeira.isalpha() and primeira != "br":
        return primeira
    return uf_padrao


def parse_linha(row, uf_padrao, tipo):
    # Le uma linha da tabela e devolve um dicionario com os dados do concurso,
    # ou None se a linha nao for um concurso de verdade.
    a = _RE_ANCORA.search(row)
    if not a:
        return None
    atributos, interno = a.group(1), a.group(2)

    link = _atributo(atributos, "href")
    # So aceitamos links de concurso (que tem data no caminho). Isso descarta
    # links de menu e de navegacao que tambem usam /concursos/.
    if "/concursos/" not in link or not _RE_DATA.search(link):
        return None

    orgao = _limpa(interno)
    if not orgao:
        return None

    titulo = _limpa(_atributo(atributos, "title"))

    # As vagas ficam em uma celula seguinte (a primeira celula tem o link).
    vagas = ""
    celulas = _RE_TD.findall(row)
    for td in celulas[1:]:
        valor = _limpa(td)
        if valor:
            vagas = valor
            break

    return {
        "orgao": orgao,
        "titulo": titulo,
        "vagas": vagas,
        "link": link,
        "uf": _uf_do_link(link, uf_padrao),
        "data": _data_do_link(link),
        "tipo": tipo,
    }


def _chave(orgao, uf, data_fim=""):
    # Chave para deduplicar o MESMO concurso entre fontes diferentes.
    #
    # Inclui a data de encerramento porque um mesmo orgao costuma ter varios
    # concursos distintos ao mesmo tempo (cargos/editais diferentes). Sem a data,
    # esses concursos distintos seriam fundidos por engano. Sem data_fim a chave
    # fica vazia, e o item nao se funde com ninguem (melhor mostrar do que
    # esconder um concurso real).
    if not data_fim:
        return ""
    # As fontes nomeiam o orgao de formas diferentes. O PCI costuma usar
    # "SIGLA - Nome por extenso" ou "Cidade/UF"; o Concursos no Brasil usa so a
    # sigla ou o nome curto. Pegamos a parte ANTES do " - " ou "/", que e o
    # identificador comum (sigla ou cidade), e normalizamos.
    nome = re.split(r"\s[-–]\s|/", orgao or "", maxsplit=1)[0]
    s = db.remover_acentos(nome.lower())
    s = re.sub(r"\bpref\.?\b", "prefeitura", s)
    s = re.sub(r"\bcam\.?\b", "camara", s)
    s = re.sub(r"\bgov\.?\b", "governo", s)
    s = re.sub(r"\b(de|da|do|das|dos|e)\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Tira um token de UF que tenha sobrado no fim do nome.
    s = re.sub(r"\s+" + re.escape((uf or "").lower()) + r"$", "", s)
    return f"{s}|{(uf or '').lower()}|{data_fim}"


def _para_linha_db(item, fonte="Concursos no Brasil"):
    # Converte o item lido para o formato gravado no banco.
    link = item["link"]
    # Dedupe pelo link, que e unico por concurso.
    h = hashlib.sha1(link.encode("utf-8")).hexdigest()
    situacao = "Inscricoes abertas" if item["tipo"] == "aberto" else "Concurso previsto"

    # Blob com todo o texto util (inclui o titulo rico) para busca e filtro de
    # area. Removemos acentos (busca insensivel a acento) e trocamos pontuacao
    # por espaco para a busca por palavra inteira casar bem.
    partes = [item["orgao"], item["titulo"], item["vagas"], item["uf"], item["tipo"]]
    blob = db.remover_acentos(" ".join(p.lower() for p in partes if p))
    blob = re.sub(r"[^0-9a-z ]+", " ", blob)
    blob = re.sub(r"\s+", " ", blob).strip()

    uf = (item["uf"] or "br").lower()
    return {
        "hash": h,
        "uf": uf,
        "orgao": item["orgao"],
        "titulo": item["titulo"],
        "situacao": situacao,
        "link": link,
        "vagas": item["vagas"],
        "tipo": item["tipo"],
        "data": item["data"],
        "fonte": fonte,
        "chave": _chave(item["orgao"], uf, item.get("data_fim", "")),
        "blob": blob,
        "raw_json": json.dumps(item, ensure_ascii=False),
    }


def _get_com_retry(client, url, tentativas=None, timeout=40, **kwargs):
    # GET com retry e backoff exponencial. Levanta a ultima excecao se todas as
    # tentativas falharem (quem chama decide se ignora). Uma falha de rede
    # passageira deixa de derrubar a coleta daquela pagina.
    tentativas = tentativas or HTTP_TENTATIVAS
    espera = HTTP_BACKOFF
    ultimo_erro = None
    for i in range(tentativas):
        try:
            resp = client.get(url, timeout=timeout, follow_redirects=True, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as erro:
            ultimo_erro = erro
            if i < tentativas - 1:
                time.sleep(espera)
                espera *= 2
    raise ultimo_erro


def _baixar(client, url):
    # Baixa uma pagina e devolve o HTML decodificado em utf-8.
    resp = _get_com_retry(client, url)
    return resp.content.decode("utf-8", "replace")


def _coletar_abertos(client, url, uf_padrao, novos_out=None):
    # Le uma pagina de concursos abertos e grava cada item. Retorna (novos, total).
    # Os itens novos sao acumulados em novos_out (para as notificacoes).
    novos = 0
    total = 0
    try:
        html = _baixar(client, url)
    except Exception as erro:
        print(f"[coleta] falha em {url}: {erro}")
        return 0, 0

    for row in _RE_LINHA.findall(html):
        item = parse_linha(row, uf_padrao, "aberto")
        if not item:
            continue
        total += 1
        if db.upsert_concurso(_para_linha_db(item)):
            novos += 1
            if novos_out is not None:
                novos_out.append(item)

    return novos, total


def coletar_uf(client, uf, novos_out=None):
    # Coleta os concursos abertos de um estado.
    return _coletar_abertos(client, f"{BASE_URL}/concursos/{uf}/", uf, novos_out)


def coletar_abertos_nacional(client, novos_out=None):
    # Coleta a pagina principal de abertos, que traz concursos nacionais
    # (Exercito, Marinha, orgaos federais) que nao aparecem nas paginas de
    # estado. Sem ela, esses concursos abertos ficariam de fora ou marcados
    # apenas como previstos.
    return _coletar_abertos(client, f"{BASE_URL}/concursos/", "br", novos_out)


def coletar_previstos(client, novos_out=None):
    # Coleta os concursos previstos (pagina nacional), pegando os mais recentes.
    url = f"{BASE_URL}/concursos/previstos/"
    try:
        html = _baixar(client, url)
    except Exception as erro:
        print(f"[coleta] falha em previstos: {erro}")
        return 0, 0

    itens = []
    for row in _RE_LINHA.findall(html):
        item = parse_linha(row, "br", "previsto")
        if item:
            itens.append(item)

    # Ordena pelos mais recentes (data no link) e limita a quantidade.
    itens.sort(key=lambda x: x["data"], reverse=True)
    itens = itens[:MAX_PREVISTOS]

    novos = 0
    for item in itens:
        if db.upsert_concurso(_para_linha_db(item)):
            novos += 1
            if novos_out is not None:
                novos_out.append(item)
    return novos, len(itens)


def coletar_tudo():
    # Coleta a listagem, protegida pela trava: se ja houver uma coleta em
    # andamento (boot ou outra rodada do agendador), pula esta sem bloquear.
    if not _LOCK_COLETA.acquire(blocking=False):
        print("[coleta] ja existe uma coleta em andamento; pulando esta rodada")
        return {"itens": 0, "novos": 0, "quando": None, "pulado": True}
    try:
        return _coletar_tudo()
    finally:
        _LOCK_COLETA.release()


def _coletar_tudo():
    # Percorre os 27 estados (abertos) e a pagina de previstos, gravando tudo.
    inicio = datetime.now().isoformat(timespec="seconds")
    print(f"[coleta] iniciando em {inicio}")

    total_novos = 0
    total_itens = 0
    novos_itens = []
    headers = {"User-Agent": USER_AGENT}

    with httpx.Client(headers=headers, follow_redirects=True) as client:
        # Coleta os previstos primeiro. Assim, se um concurso aparecer tambem
        # na lista de abertos de um estado (mesmo link), o tipo "aberto" e
        # gravado por ultimo e prevalece, que e o estado atual correto.
        novos, total = coletar_previstos(client, novos_itens)
        total_novos += novos
        total_itens += total
        print(f"[coleta] previstos: {total} itens, {novos} novos")
        time.sleep(PAUSA_SEGUNDOS)

        # Abertos nacionais (orgaos federais que nao estao nas paginas de estado).
        novos, total = coletar_abertos_nacional(client, novos_itens)
        total_novos += novos
        total_itens += total
        print(f"[coleta] abertos nacionais: {total} itens, {novos} novos")
        time.sleep(PAUSA_SEGUNDOS)

        for uf in UFS:
            novos, total = coletar_uf(client, uf, novos_itens)
            total_novos += novos
            total_itens += total
            print(f"[coleta] {uf}: {total} abertos, {novos} novos")
            time.sleep(PAUSA_SEGUNDOS)

        # Segunda fonte: PCI Concursos (amplia a cobertura).
        novos, total = coletar_pci(client, novos_itens)
        total_novos += novos
        total_itens += total
        time.sleep(PAUSA_SEGUNDOS)

    fim = datetime.now().isoformat(timespec="seconds")
    resultado = f"{total_itens} itens vistos, {total_novos} novos"

    db.set_meta("ultima_coleta", fim)
    db.set_meta("ultimo_resultado", resultado)

    # Notifica os novos concursos que casam com o perfil (so depois da primeira
    # coleta, para nao disparar uma enxurrada quando o banco e populado do zero).
    try:
        notificar_novos(novos_itens)
    except Exception as erro:
        print(f"[notify] erro ao notificar: {erro}")
    db.set_meta("coleta_inicial_feita", "1")

    print(f"[coleta] concluida: {resultado}")
    return {"itens": total_itens, "novos": total_novos, "quando": fim}


# ----------------------------------------------------------------------------
# Enriquecimento por pagina de detalhe (data de encerramento, link e PDF)
# ----------------------------------------------------------------------------

def _texto_visivel(html):
    # Remove scripts/estilos e tags, devolvendo o texto corrido da pagina.
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S)
    texto = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", texto)


def _mes_num(nome):
    # Converte o nome do mes (com ou sem acento) para numero.
    return _MESES.get(db.remover_acentos(nome.lower()))


def _extrair_periodo(texto):
    # Extrai (data_inicio, data_fim) das frases de inscricao, em AAAA-MM-DD.
    # Procura as datas perto da palavra "inscri" para evitar datas soltas.
    janelas = []
    low = texto.lower()
    for m in re.finditer("inscri", low):
        janelas.append(texto[max(0, m.start() - 30): m.start() + 220])
        if len(janelas) >= 2:
            break
    trecho = " ".join(janelas) if janelas else texto[:500]

    achados = []
    for m in _RE_DATA_PT.finditer(trecho):
        mes = _mes_num(m.group(2))
        if not mes:
            continue
        ano = int(m.group(3)) if m.group(3) else None
        achados.append((int(m.group(1)), mes, ano))
    if not achados:
        return "", ""

    # Completa o ano faltante usando o ano de alguma data vizinha (ou o atual).
    anos = [a for (_, _, a) in achados if a]
    ano_ref = anos[0] if anos else datetime.now().year
    isos = sorted(
        {f"{(a or ano_ref):04d}-{mes:02d}-{dia:02d}" for (dia, mes, a) in achados}
    )
    if len(isos) >= 2:
        return isos[0], isos[-1]
    # So uma data: tratamos como a data de encerramento.
    return "", isos[0]


_REDES = (
    "facebook", "twitter", "x.com", "whatsapp", "wa.me", "t.me", "telegram",
    "instagram", "linkedin", "youtube", "/share", "pinterest",
)


def _achar_link_oficial(html):
    # Pega o link externo mais provavel de ser o oficial (portal/edital).
    # A secao "Leia tambem" so tem links internos do proprio site, entao
    # procurar links EXTERNOS na pagina toda e seguro e mais abrangente.
    candidatos = []
    for m in re.finditer(r'<a\s+[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href = m.group(1)
        if "concursosnobrasil" in href:
            continue
        if any(s in href.lower() for s in _REDES):
            continue
        texto = re.sub(r"<[^>]+>", " ", m.group(2)).strip().lower()
        candidatos.append((href, texto))

    def pontos(item):
        href, texto = item
        s = 0
        if href.lower().split("?")[0].endswith(".pdf"):
            s += 4
        if ".gov.br" in href:
            s += 3
        if any(k in (texto + " " + href).lower()
               for k in ("edital", "inscri", "portal", "concurso", "selet")):
            s += 2
        return s

    # So aceita links que pareçam de fato oficiais (pontuacao > 0), para nao
    # pegar um link qualquer de rodape.
    candidatos = [c for c in candidatos if pontos(c) > 0]
    candidatos.sort(key=pontos, reverse=True)
    return candidatos[0][0] if candidatos else ""


def _achar_pdf(client, link_oficial):
    # Best-effort: se o link oficial ja for um PDF, usa; senao abre a pagina
    # oficial e procura um link de PDF (de preferencia que cite "edital").
    if not link_oficial:
        return ""
    if link_oficial.lower().split("?")[0].endswith(".pdf"):
        return link_oficial
    try:
        r = client.get(link_oficial, timeout=20, follow_redirects=True)
        if "pdf" in r.headers.get("content-type", "").lower():
            return str(r.url)
        html = r.content.decode("utf-8", "replace")
        base = str(r.url)
    except Exception:
        return ""

    candidatos = []
    for m in re.finditer(r'href="([^"]+\.pdf[^"]*)"', html, re.I):
        candidatos.append(urljoin(base, m.group(1)))
    if not candidatos:
        return ""
    candidatos.sort(key=lambda h: ("edital" in h.lower()), reverse=True)
    return candidatos[0]


def _ler_pdf(client, pdf_url):
    # Baixa e extrai o texto do PDF (com limites de tamanho e de paginas).
    try:
        r = client.get(pdf_url, timeout=30, follow_redirects=True)
        conteudo = r.content
        if not conteudo[:5] == b"%PDF-" and "pdf" not in r.headers.get("content-type", "").lower():
            return ""
        if len(conteudo) > PDF_MAX_BYTES:
            conteudo = conteudo[:PDF_MAX_BYTES]
        from pypdf import PdfReader  # importado aqui para nao pesar o boot
        leitor = PdfReader(BytesIO(conteudo))
        partes = []
        for pagina in leitor.pages[:PDF_MAX_PAGINAS]:
            try:
                partes.append(pagina.extract_text() or "")
            except Exception:
                continue
        return " ".join(partes)
    except Exception:
        return ""


def _folder_blob(texto):
    # Normaliza um texto para virar blob de busca (sem acento, so palavras).
    bd = db.remover_acentos(texto.lower())
    bd = re.sub(r"[^0-9a-z ]+", " ", bd)
    return re.sub(r"\s+", " ", bd).strip()


# Bancas organizadoras mais comuns, para identificar quem organiza o concurso.
# Evitamos nomes ambiguos (ex: "Objetiva" casa com "prova objetiva").
_BANCAS = [
    "Cebraspe", "CESPE", "FGV", "FCC", "Vunesp", "IBFC", "Quadrix", "AOCP",
    "Idecan", "Consulplan", "Cetro", "Fundep", "Fundatec", "IADES", "Ibade",
    "Selecon", "Legalle", "FAURGS", "Itame", "Fafipa", "Gualimp",
    "Avança SP", "Instituto Access", "Instituto Mais", "FUNRIO", "FEPESE",
    "Konsentec", "CONSESP", "UNOESC", "Unifil", "Aroeira", "IBAM", "IDIB",
]


def _corpo_artigo(html):
    # Junta o texto dos paragrafos <p> da pagina. A materia em si fica em <p>,
    # enquanto a caixa "Leia tambem" usa listas de links (<a>), entao isso
    # extrai o conteudo real e descarta o ruido dos concursos relacionados.
    paragrafos = re.findall(r"<p[^>]*>(.*?)</p>", html, re.S)
    texto = " ".join(re.sub(r"<[^>]+>", " ", p) for p in paragrafos)
    return re.sub(r"\s+", " ", texto).strip()


def _extrair_detalhes(corpo):
    # Extrai informacoes extras do corpo do artigo: banca, escolaridade,
    # salario, taxa de inscricao e data da prova. Tudo best-effort.
    d = {}

    for banca in _BANCAS:
        if re.search(r"\b" + re.escape(banca) + r"\b", corpo, re.I):
            d["banca"] = banca
            break

    niveis = []
    for rotulo, padrao in (("fundamental", "fundamental"), ("medio", r"m[ée]dio"),
                           ("tecnico", r"t[ée]cnico"), ("superior", "superior")):
        if re.search(r"(?:n[íi]vel|ensino|escolaridade)[^.]{0,30}" + padrao, corpo, re.I):
            niveis.append(rotulo)
    if niveis:
        d["escolaridade"] = ", ".join(dict.fromkeys(niveis))

    m = re.search(
        r"(?:sal[áa]rio|remunera\w+|vencimento).{0,40}?(R\$\s*[\d.,]+(?:\s*mil)?)",
        corpo, re.I,
    )
    if m:
        d["salario"] = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".,")

    m = re.search(r"taxa.{0,40}?(R\$\s*[\d.,]+)", corpo, re.I)
    if m:
        d["taxa"] = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".,")

    m = re.search(
        r"(?:prova|aplica\w+)[^.]{0,40}?(\d{1,2}\s+de\s+"
        r"(?:janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|"
        r"setembro|outubro|novembro|dezembro)(?:\s+de\s+\d{4})?)",
        corpo, re.I,
    )
    if m:
        d["data_prova"] = re.sub(r"\s+", " ", m.group(1)).strip()

    return d


def enriquecer_um(client, concurso):
    # Le a pagina de detalhe de um concurso e grava data de inscricao, link
    # oficial, resumo e, se possivel, o PDF do edital (link + texto lido).
    dados = {
        "data_inicio": "", "data_fim": "", "link_oficial": "",
        "pdf_url": "", "resumo": "", "detalhes_json": "", "blob_detalhe": "",
    }
    try:
        r = client.get(concurso["link"], timeout=25, follow_redirects=True)
        html = r.content.decode("utf-8", "replace")
    except Exception as erro:
        # Marca como tentado para nao ficar repetindo uma pagina problematica.
        db.atualizar_detalhe(concurso["hash"], dados)
        print(f"[detalhe] falha ao abrir {concurso['link']}: {erro}")
        return False

    texto = _texto_visivel(html)
    corpo = _corpo_artigo(html)
    # Prefere as datas do corpo da materia; se nao achar, tenta no texto todo.
    di, dfim = _extrair_periodo(corpo)
    if not dfim:
        di, dfim = _extrair_periodo(texto)
    dados["data_inicio"], dados["data_fim"] = di, dfim
    dados["link_oficial"] = _achar_link_oficial(html)

    # Informacoes extras (banca, escolaridade, salario, taxa, data da prova).
    detalhes = _extrair_detalhes(corpo)
    partes_blob = [_folder_blob(" ".join(detalhes.values()))] if detalhes else []

    if LER_PDF and dados["link_oficial"]:
        pdf = _achar_pdf(client, dados["link_oficial"])
        if pdf:
            dados["pdf_url"] = pdf
            texto_pdf = _ler_pdf(client, pdf)
            if texto_pdf:
                partes_blob.append(_folder_blob(texto_pdf)[:6000])
                # Se nao achamos a data na pagina, tentamos dentro do PDF.
                if not dados["data_fim"]:
                    di, dfim = _extrair_periodo(texto_pdf)
                    if dfim:
                        dados["data_fim"] = dfim
                    if di and not dados["data_inicio"]:
                        dados["data_inicio"] = di
                # Completa detalhes que faltaram, usando o texto do PDF.
                for chave, valor in _extrair_detalhes(texto_pdf).items():
                    detalhes.setdefault(chave, valor)

    if detalhes:
        dados["detalhes_json"] = json.dumps(detalhes, ensure_ascii=False)
    dados["blob_detalhe"] = " ".join(p for p in partes_blob if p)[:7000]
    # Agora que sabemos a data de encerramento, recalculamos a chave de dedupe
    # (orgao + uf + data_fim) para casar com a mesma vaga vinda de outra fonte.
    if dados["data_fim"]:
        dados["chave"] = _chave(concurso.get("orgao", ""), concurso.get("uf", ""),
                                dados["data_fim"])

    db.atualizar_detalhe(concurso["hash"], dados)
    return True


def enriquecer_lote(limite=None):
    # Enriquece um lote de concursos ainda sem detalhe (PA e abertos primeiro).
    limite = limite or LOTE_DETALHES
    pendentes = db.concursos_para_detalhar(limite)
    if not pendentes:
        return 0

    headers = {"User-Agent": USER_AGENT}
    feitos = 0
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        for concurso in pendentes:
            try:
                enriquecer_um(client, concurso)
                feitos += 1
            except Exception as erro:
                print(f"[detalhe] erro em {concurso.get('link')}: {erro}")
            time.sleep(PAUSA_DETALHE)

    print(f"[detalhe] enriquecidos {feitos} concursos neste lote")
    return feitos


def enriquecer_tudo():
    # Enriquece TODOS os concursos pendentes, em lotes, ate acabar. Usado no
    # boot e na leitura diaria das 4h. Pode demorar, por isso roda fora do
    # caminho das requisicoes.
    total = 0
    while True:
        feitos = enriquecer_lote(LOTE_DETALHES)
        total += feitos
        if feitos < LOTE_DETALHES:
            break
        time.sleep(1)
    print(f"[detalhe] leitura completa de editais: {total} concursos")
    return total


def coletar_e_enriquecer():
    # Coleta a listagem e em seguida le todos os editais. Usado no boot e no
    # agendamento diario das 4h. Segura a trava durante TODO o processo (coleta
    # + leitura pesada), entao a coleta horaria que cair no meio simplesmente
    # pula em vez de competir pela escrita no banco.
    if not _LOCK_COLETA.acquire(blocking=False):
        print("[coleta] ja existe uma coleta em andamento; pulando leitura diaria")
        return
    try:
        _coletar_tudo()
        enriquecer_tudo()
    finally:
        _LOCK_COLETA.release()


# ----------------------------------------------------------------------------
# Perfil de interesse e notificacoes (ntfy)
# ----------------------------------------------------------------------------

def carregar_perfil():
    # Le o perfil de interesse salvo (UFs, termos, areas e config de ntfy).
    import json as _json
    try:
        return _json.loads(db.get_meta("perfil") or "{}")
    except Exception:
        return {}


def _casa_perfil(item, perfil):
    # Verdadeiro se o concurso casa com algum interesse do perfil (OU logico).
    ufs = [u.lower() for u in perfil.get("ufs", []) if u]
    termos = [db.remover_acentos(t.lower()) for t in perfil.get("termos", []) if t and t.strip()]
    areas = perfil.get("areas", [])
    if not (ufs or termos or areas):
        return False

    if ufs and (item.get("uf", "").lower() in ufs):
        return True

    blob = db.remover_acentos(
        f"{item.get('orgao','')} {item.get('titulo','')} {item.get('uf','')}".lower()
    )
    if termos and any(t in blob for t in termos):
        return True
    if areas:
        from .areas import AREAS
        for area in areas:
            for palavra in AREAS.get(area, []):
                if db.remover_acentos(palavra.lower()) in blob:
                    return True
    return False


def _ascii(texto):
    # Cabecalhos do ntfy precisam ser ASCII; tiramos os acentos.
    return db.remover_acentos(texto)


def _enviar_ntfy(perfil, titulo, corpo, link=""):
    # Envia uma notificacao para o topico ntfy configurado no perfil.
    topico = (perfil.get("ntfy_topico") or "").strip()
    if not topico:
        return False
    servidor = (perfil.get("ntfy_server") or "https://ntfy.sh").rstrip("/")
    headers = {"Title": _ascii(titulo), "Tags": "mega"}
    link = link or perfil.get("app_url") or ""
    if link:
        headers["Click"] = link
    try:
        httpx.post(f"{servidor}/{topico}", data=corpo.encode("utf-8"),
                   headers=headers, timeout=10)
        return True
    except Exception as erro:
        print(f"[ntfy] erro: {erro}")
        return False


def notificar_novos(novos_itens):
    # Notifica, via ntfy, os concursos novos que casam com o perfil. Nao
    # dispara na primeira coleta (quando o banco e populado do zero).
    perfil = carregar_perfil()
    if not perfil.get("notificar"):
        return
    if not db.get_meta("coleta_inicial_feita"):
        return
    matches = [it for it in novos_itens if _casa_perfil(it, perfil)]
    if not matches:
        return

    if len(matches) <= 5:
        for it in matches:
            titulo = f"Novo concurso: {it.get('orgao','')} ({it.get('uf','').upper()})"
            corpo = it.get("titulo") or it.get("orgao") or "Novo concurso"
            _enviar_ntfy(perfil, titulo, corpo, it.get("link", ""))
    else:
        titulo = f"{len(matches)} novos concursos do seu interesse"
        corpo = "\n".join(
            f"- {it.get('orgao','')} ({it.get('uf','').upper()})" for it in matches[:12]
        )
        _enviar_ntfy(perfil, titulo, corpo)
    print(f"[notify] {len(matches)} concursos notificados")


def verificar_prazos_favoritos():
    # Lembrete: avisa, via ntfy, quando um concurso favoritado esta perto de
    # encerrar as inscricoes. Roda uma vez por dia.
    perfil = carregar_perfil()
    if not perfil.get("notificar") or not perfil.get("ntfy_topico"):
        return
    dias = int(os.environ.get("PRAZO_AVISO_DIAS", "3"))
    favoritos = db.favoritos_para_avisar(dias)
    from datetime import date
    for c in favoritos:
        try:
            restam = (date.fromisoformat(c["data_fim"]) - date.today()).days
        except Exception:
            restam = None
        quando = "hoje" if restam == 0 else (f"em {restam} dias" if restam else "em breve")
        titulo = f"Prazo: {c.get('orgao','')}"
        corpo = f"As inscricoes encerram {quando} ({c.get('data_fim','')})."
        _enviar_ntfy(perfil, titulo, corpo, c.get("link", ""))
        db.marcar_prazo_avisado(c["hash"])
    if favoritos:
        print(f"[prazo] avisados {len(favoritos)} favoritos")


def enviar_notificacao_teste(perfil):
    # Envia uma notificacao de teste para validar a configuracao do ntfy.
    return _enviar_ntfy(
        perfil,
        "Rastreador de Concursos",
        "Funcionou! Voce vai receber aqui os novos concursos do seu interesse.",
    )


# ----------------------------------------------------------------------------
# Provas anteriores (PCI Concursos) para treinar
# ----------------------------------------------------------------------------

PCI_BASE = "https://www.pciconcursos.com.br"
PCI_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120 Safari/537.36")


def _slug(termo):
    # Transforma um termo em slug do PCI (ex: "Agente Administrativo" ->
    # "agente-administrativo").
    s = db.remover_acentos(termo.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def buscar_provas(termo, limite=40):
    # Busca provas anteriores no PCI Concursos por cargo/termo. Respeita o
    # robots: nao baixa os PDFs, apenas lista e devolve o link da pagina de
    # download do PCI (onde o usuario baixa).
    slug = _slug(termo) if termo else "top"
    url = f"{PCI_BASE}/provas/{slug}"
    try:
        r = httpx.get(url, headers={"User-Agent": PCI_UA}, timeout=25,
                      follow_redirects=True)
        if r.status_code != 200:
            return {"url": url, "provas": []}
        html = r.content.decode("utf-8", "replace")
    except Exception as erro:
        print(f"[provas] erro: {erro}")
        return {"url": url, "provas": []}

    provas = []
    for m in re.finditer(r'<tr[^>]*data-url="([^"]+)"[^>]*>(.*?)</tr>', html, re.S):
        link = m.group(1)
        celulas = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", m.group(2), re.S)
        ]
        if len(celulas) >= 4:
            provas.append({
                "prova": celulas[0], "ano": celulas[1],
                "orgao": celulas[2], "banca": celulas[3], "url": link,
            })
        if len(provas) >= limite:
            break
    return {"url": url, "provas": provas}


# ----------------------------------------------------------------------------
# Segunda fonte: PCI Concursos (lista de concursos abertos)
# ----------------------------------------------------------------------------

PCI_CONCURSOS_URL = f"{PCI_BASE}/concursos/"


def _parse_pci(bloco):
    # Le um bloco de concurso da listagem do PCI. Retorna o item normalizado.
    a = re.search(r'<a\s+href="([^"]+)"[^>]*?title="([^"]*)"[^>]*>(.*?)</a>', bloco, re.S)
    if not a:
        return None
    link = a.group(1)
    if "pciconcursos" not in link:
        return None
    titulo = re.sub(r"\s+", " ", a.group(2)).strip()
    orgao = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", a.group(3))).strip()
    if not orgao:
        return None

    texto = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", bloco)).strip()

    mv = re.search(r"(\d[\d.]*)\s+vagas?", texto)
    vagas = (mv.group(1) + " vagas") if mv else ""

    ms = re.search(r"R\$\s*[\d.,]+", texto)

    md = re.search(r"(\d{2})/(\d{2})/(\d{4})", texto)
    data_fim = f"{md.group(3)}-{md.group(2)}-{md.group(1)}" if md else ""

    niveis = []
    for rotulo, padrao in (("fundamental", "Fundamental"), ("medio", r"M[ée]dio"),
                           ("tecnico", r"T[ée]cnico"), ("superior", "Superior")):
        if re.search(r"\b" + padrao + r"\b", texto):
            niveis.append(rotulo)

    muf = re.search(r"[/\-]\s*([A-Z]{2})\b", orgao + " | " + titulo)
    uf = muf.group(1).lower() if muf else "br"

    detalhes = {}
    if niveis:
        detalhes["escolaridade"] = ", ".join(dict.fromkeys(niveis))
    if ms:
        detalhes["salario"] = ms.group(0)

    return {
        "orgao": orgao, "titulo": titulo, "vagas": vagas, "link": link,
        "uf": uf, "data": "", "tipo": "aberto",
        "data_fim": data_fim, "detalhes": detalhes,
    }


def coletar_pci(client, novos_out=None):
    # Coleta a lista de concursos abertos do PCI Concursos (segunda fonte).
    # Os itens ja vem com prazo e escolaridade, entao gravamos o detalhe na hora
    # e marcamos como lidos (nao precisam do enriquecimento por pagina).
    try:
        r = _get_com_retry(client, PCI_CONCURSOS_URL,
                           headers={"User-Agent": PCI_UA}, timeout=30)
        html = r.content.decode("utf-8", "replace")
    except Exception as erro:
        print(f"[pci] falha: {erro}")
        return 0, 0

    novos = 0
    total = 0
    for bloco in html.split('<div class="ca">')[1:]:
        item = _parse_pci(bloco)
        if not item:
            continue
        total += 1
        norm = _para_linha_db(item, fonte="PCI Concursos")
        novo = db.upsert_concurso(norm)
        db.atualizar_detalhe(norm["hash"], {
            "data_inicio": "", "data_fim": item["data_fim"],
            "link_oficial": "", "pdf_url": "", "resumo": "",
            "detalhes_json": json.dumps(item.get("detalhes", {}), ensure_ascii=False),
            "blob_detalhe": _folder_blob(" ".join(str(v) for v in item.get("detalhes", {}).values())),
        })
        if novo:
            novos += 1
            if novos_out is not None:
                novos_out.append(item)

    print(f"[pci] {total} itens, {novos} novos")
    return novos, total
