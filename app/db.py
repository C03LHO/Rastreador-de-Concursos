"""Camada de acesso ao banco SQLite.

Aqui ficam a criacao das tabelas, o upsert dos concursos, a busca com filtros
e o controle dos metadados de coleta (ultima_coleta e ultimo_resultado).

Cada operacao abre e fecha a sua propria conexao. Isso e simples e seguro para
o uso simultaneo entre as threads do scheduler e as requisicoes da API.
"""

import glob
import os
import sqlite3
import unicodedata
from datetime import datetime

# Caminho do arquivo do banco. Em Docker apontamos para /data/concursos.db via
# variavel de ambiente para o arquivo ficar no volume persistido.
DB_PATH = os.environ.get("DB_PATH", "concursos.db")

# Marca do modelo de dados / fonte atual. Se mudar, os dados antigos (por
# exemplo, os da API anterior, que nao tinham link) sao limpos no boot.
VERSAO_FONTE = "concursosnobrasil-v6-entidades-html"


def remover_acentos(texto):
    # Remove acentos para a busca ser insensivel a eles (ex: "saude" acha
    # "saude" e "saude"). Usado tanto no blob gravado quanto nos termos de busca.
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def conectar():
    # Abre uma conexao nova. row_factory deixa as linhas acessiveis por nome.
    # busy_timeout (via timeout) faz a conexao esperar em vez de falhar quando
    # outra esta escrevendo.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _aplicar_pragmas():
    # WAL permite leituras simultaneas enquanto a coleta/enriquecimento escreve,
    # evitando travas e lentidao quando o app serve requisicoes e grava ao mesmo
    # tempo. So precisa ser definido uma vez (fica gravado no arquivo).
    conn = conectar()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.commit()
    finally:
        conn.close()


def iniciar_banco():
    # Cria as tabelas caso ainda nao existam e aplica migracoes simples.
    _aplicar_pragmas()
    conn = conectar()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS concursos (
                hash TEXT PRIMARY KEY,
                uf TEXT,
                orgao TEXT,
                titulo TEXT,
                situacao TEXT,
                link TEXT,
                vagas TEXT,
                tipo TEXT,
                data TEXT,
                fonte TEXT,
                chave TEXT,
                data_inicio TEXT,
                data_fim TEXT,
                link_oficial TEXT,
                pdf_url TEXT,
                resumo TEXT,
                detalhes_json TEXT,
                blob TEXT,
                blob_detalhe TEXT,
                raw_json TEXT,
                detalhe_em TEXT,
                primeira_vez TEXT,
                atualizado_em TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                chave TEXT PRIMARY KEY,
                valor TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS favoritos (
                hash TEXT PRIMARY KEY,
                criado_em TEXT,
                prazo_avisado TEXT
            )
            """
        )

        # Migracao: adiciona colunas novas em bancos criados em versoes antigas.
        existentes = {r["name"] for r in conn.execute("PRAGMA table_info(concursos)")}
        novas = (
            "titulo", "data", "fonte", "chave", "data_inicio", "data_fim",
            "link_oficial", "pdf_url", "resumo", "detalhes_json",
            "blob_detalhe", "detalhe_em",
        )
        for coluna in novas:
            if coluna not in existentes:
                conn.execute(f"ALTER TABLE concursos ADD COLUMN {coluna} TEXT")

        # Indices simples para acelerar os filtros mais comuns.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_concursos_uf ON concursos(uf)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_concursos_tipo ON concursos(tipo)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_concursos_chave ON concursos(chave)")

        # Troca de fonte: se o modelo mudou, limpa os concursos antigos para
        # nao misturar dados sem link com os novos.
        cur = conn.execute("SELECT valor FROM meta WHERE chave = 'fonte_versao'")
        row = cur.fetchone()
        if (row["valor"] if row else None) != VERSAO_FONTE:
            conn.execute("DELETE FROM concursos")
            conn.execute(
                """
                INSERT INTO meta (chave, valor) VALUES ('fonte_versao', ?)
                ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
                """,
                (VERSAO_FONTE,),
            )

        conn.commit()
    finally:
        conn.close()


def upsert_concurso(item):
    # Insere ou atualiza um concurso pelo hash. Retorna True se for novo.
    conn = conectar()
    try:
        agora = datetime.now().isoformat(timespec="seconds")
        cur = conn.execute(
            "SELECT hash FROM concursos WHERE hash = ?", (item["hash"],)
        )
        existe = cur.fetchone() is not None

        if existe:
            # Ja existe: atualiza os campos e a data de atualizacao.
            # Importante: a chave de dedup so e preenchida no enriquecimento
            # (quando a data_fim e conhecida). Na coleta da listagem ela vem
            # vazia, entao NUNCA sobrescrevemos uma chave ja calculada com vazio
            # -- senao a deduplicacao entre fontes quebraria a cada coleta
            # horaria. COALESCE(NULLIF(...)) preserva a chave existente.
            conn.execute(
                """
                UPDATE concursos
                SET uf = ?, orgao = ?, titulo = ?, situacao = ?, link = ?,
                    vagas = ?, tipo = ?, data = ?, fonte = ?,
                    chave = COALESCE(NULLIF(?, ''), chave),
                    blob = ?, raw_json = ?, atualizado_em = ?
                WHERE hash = ?
                """,
                (
                    item["uf"], item["orgao"], item["titulo"], item["situacao"],
                    item["link"], item["vagas"], item["tipo"], item["data"],
                    item.get("fonte", ""), item.get("chave", ""),
                    item["blob"], item["raw_json"], agora, item["hash"],
                ),
            )
        else:
            # Novo: insere e marca primeira_vez igual a atualizado_em.
            conn.execute(
                """
                INSERT INTO concursos
                    (hash, uf, orgao, titulo, situacao, link, vagas, tipo, data,
                     fonte, chave, blob, raw_json, primeira_vez, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["hash"], item["uf"], item["orgao"], item["titulo"],
                    item["situacao"], item["link"], item["vagas"], item["tipo"],
                    item["data"], item.get("fonte", ""), item.get("chave", ""),
                    item["blob"], item["raw_json"], agora, agora,
                ),
            )
        conn.commit()
        return not existe
    finally:
        conn.close()


def concursos_para_detalhar(limite):
    # Lista os concursos que ainda nao foram enriquecidos com a pagina de
    # detalhe. Prioriza Para (foco pedido), depois abertos e mais recentes.
    conn = conectar()
    try:
        cur = conn.execute(
            """
            SELECT hash, link, uf, tipo, orgao, detalhes_json FROM concursos
            WHERE detalhe_em IS NULL OR detalhe_em = ''
            ORDER BY (uf = 'pa') DESC,
                     (tipo = 'aberto') DESC,
                     data DESC
            LIMIT ?
            """,
            (int(limite),),
        )
        return [dict(linha) for linha in cur.fetchall()]
    finally:
        conn.close()


def atualizar_detalhe(hash_, dados, marcar_lido=True):
    # Grava os campos extraidos da pagina de detalhe e do PDF do edital.
    #
    # COALESCE(NULLIF(?, '')) preserva o valor que ja existe quando o novo vem
    # vazio: assim uma leitura que nao reencontrou um campo (ex: a data) nao
    # apaga o que ja sabiamos. marcar_lido=False grava dados iniciais (ex: da
    # listagem do PCI) SEM tirar o item da fila de enriquecimento.
    conn = conectar()
    try:
        agora = datetime.now().isoformat(timespec="seconds")
        # detalhe_em: marca a hora (lido) ou mantem o valor atual (NULL = a ler).
        detalhe_sql = "?" if marcar_lido else "detalhe_em"
        conn.execute(
            f"""
            UPDATE concursos
            SET data_inicio = COALESCE(NULLIF(?, ''), data_inicio),
                data_fim = COALESCE(NULLIF(?, ''), data_fim),
                link_oficial = COALESCE(NULLIF(?, ''), link_oficial),
                pdf_url = COALESCE(NULLIF(?, ''), pdf_url),
                resumo = COALESCE(NULLIF(?, ''), resumo),
                detalhes_json = COALESCE(NULLIF(?, ''), detalhes_json),
                blob_detalhe = COALESCE(NULLIF(?, ''), blob_detalhe),
                chave = COALESCE(?, chave), detalhe_em = {detalhe_sql}
            WHERE hash = ?
            """,
            (
                dados.get("data_inicio", ""), dados.get("data_fim", ""),
                dados.get("link_oficial", ""), dados.get("pdf_url", ""),
                dados.get("resumo", ""), dados.get("detalhes_json", ""),
                dados.get("blob_detalhe", ""), dados.get("chave"),
                *([agora] if marcar_lido else []), hash_,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def concursos_para_ia(limite):
    # Concursos de TI (tem "cargos_ti") ja enriquecidos, mas ainda sem o resumo
    # de IA ("ia_resumo"). Usa o texto ja salvo; nao precisa baixar nada.
    conn = conectar()
    try:
        cur = conn.execute(
            """
            SELECT hash, orgao, resumo, blob_detalhe, detalhes_json
            FROM concursos
            WHERE detalhe_em IS NOT NULL AND detalhe_em <> ''
              AND detalhes_json LIKE '%"cargos_ti"%'
              AND detalhes_json NOT LIKE '%"ia_resumo"%'
            ORDER BY (uf = 'pa') DESC, (tipo = 'aberto') DESC, data DESC
            LIMIT ?
            """,
            (int(limite),),
        )
        return [dict(linha) for linha in cur.fetchall()]
    finally:
        conn.close()


def adicionar_detalhes_ia(hash_, ia):
    # Funde o resumo/plano de estudo de IA no detalhes_json existente.
    import json as _json
    conn = conectar()
    try:
        cur = conn.execute(
            "SELECT detalhes_json FROM concursos WHERE hash = ?", (hash_,))
        row = cur.fetchone()
        if not row:
            return
        try:
            det = _json.loads(row["detalhes_json"] or "{}") or {}
        except Exception:
            det = {}
        det.update(ia)
        conn.execute(
            "UPDATE concursos SET detalhes_json = ? WHERE hash = ?",
            (_json.dumps(det, ensure_ascii=False), hash_),
        )
        conn.commit()
    finally:
        conn.close()


def contar_detalhados():
    # Conta quantos concursos ja foram enriquecidos (para o status).
    conn = conectar()
    try:
        cur = conn.execute(
            "SELECT COUNT(*) AS n FROM concursos "
            "WHERE detalhe_em IS NOT NULL AND detalhe_em <> ''"
        )
        return cur.fetchone()["n"]
    finally:
        conn.close()


def buscar_concursos(uf=None, area_palavras=None, cidade=None, cargo=None,
                     tipo=None, q=None, limite=100, incluir_encerrados=False):
    # Monta a consulta dinamicamente. Todos os filtros sao combinados em E.
    clausulas = []
    params = []

    # Por padrao esconde os concursos com inscricoes ja encerradas (data_fim no
    # passado). Itens sem data de encerramento conhecida sao mantidos.
    if not incluir_encerrados:
        clausulas.append("(data_fim IS NULL OR data_fim = '' OR data_fim >= ?)")
        params.append(datetime.now().date().isoformat())

    if uf:
        clausulas.append("uf = ?")
        params.append(uf.lower())

    if tipo:
        clausulas.append("tipo = ?")
        params.append(tipo.lower())

    # A busca textual cobre o blob da listagem e o blob do detalhe (que inclui
    # o texto extraido do PDF do edital, quando lido).
    texto_sql = "(coalesce(blob,'') || ' ' || coalesce(blob_detalhe,''))"

    if cidade:
        clausulas.append(f"{texto_sql} LIKE ?")
        params.append(f"%{remover_acentos(cidade.lower())}%")

    if cargo:
        clausulas.append(f"{texto_sql} LIKE ?")
        params.append(f"%{remover_acentos(cargo.lower())}%")

    if q:
        clausulas.append(f"{texto_sql} LIKE ?")
        params.append(f"%{remover_acentos(q.lower())}%")

    if area_palavras:
        # A area casa quando QUALQUER uma das palavras aparece no texto.
        # Usamos OU entre as palavras, dentro de um grupo.
        #
        # Importante: aqui a comparacao e por PALAVRA INTEIRA, nao substring.
        # Para isso cercamos o texto e a palavra com espacos. Sem isso, a area
        # "ti" casaria dentro de "tocantins", "tiete", "aeronautica" etc.
        ors = " OR ".join(f"(' ' || {texto_sql} || ' ') LIKE ?" for _ in area_palavras)
        clausulas.append(f"({ors})")
        for palavra in area_palavras:
            params.append(f"% {remover_acentos(palavra.lower().strip())} %")

    # Deduplica entre fontes: esconde o concurso de outra fonte quando o
    # Concursos no Brasil (fonte preferida, com enriquecimento) ja tem o mesmo
    # (mesma chave = orgao + uf + data de encerramento). Nunca esconde itens da
    # mesma fonte nem os sem chave, para nao sumir com concursos distintos do
    # mesmo orgao que por acaso tenham o mesmo prazo.
    clausulas.append(
        """NOT EXISTS (
            SELECT 1 FROM concursos p
            WHERE p.chave = concursos.chave AND concursos.chave <> ''
              AND p.fonte = 'Concursos no Brasil'
              AND concursos.fonte <> 'Concursos no Brasil'
        )"""
    )

    sql = "SELECT * FROM concursos"
    if clausulas:
        sql += " WHERE " + " AND ".join(clausulas)
    sql += """
        ORDER BY (tipo = 'aberto') DESC,
                 (data_fim IS NOT NULL AND data_fim <> '') DESC,
                 data_fim ASC,
                 data DESC,
                 atualizado_em DESC
        LIMIT ?
    """
    params.append(int(limite))

    conn = conectar()
    try:
        cur = conn.execute(sql, params)
        return [dict(linha) for linha in cur.fetchall()]
    finally:
        conn.close()


def contar_total():
    # Conta quantos concursos existem no banco.
    conn = conectar()
    try:
        cur = conn.execute("SELECT COUNT(*) AS n FROM concursos")
        return cur.fetchone()["n"]
    finally:
        conn.close()


def alternar_favorito(hash_):
    # Adiciona ou remove um favorito. Retorna True se ficou favoritado.
    conn = conectar()
    try:
        cur = conn.execute("SELECT 1 FROM favoritos WHERE hash = ?", (hash_,))
        if cur.fetchone():
            conn.execute("DELETE FROM favoritos WHERE hash = ?", (hash_,))
            conn.commit()
            return False
        conn.execute(
            "INSERT INTO favoritos (hash, criado_em) VALUES (?, ?)",
            (hash_, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_concurso(hash_):
    # Le um concurso pelo hash (ou None). Usado, por exemplo, no .ics de um item.
    conn = conectar()
    try:
        cur = conn.execute("SELECT * FROM concursos WHERE hash = ?", (hash_,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def hashes_favoritos():
    # Lista os hashes favoritados (para a tela marcar as estrelas).
    conn = conectar()
    try:
        cur = conn.execute("SELECT hash FROM favoritos")
        return [r["hash"] for r in cur.fetchall()]
    finally:
        conn.close()


def listar_favoritos():
    # Devolve os concursos favoritados, ordenados pelo prazo (os que encerram
    # antes primeiro; sem data por ultimo).
    conn = conectar()
    try:
        cur = conn.execute(
            """
            SELECT c.* FROM concursos c
            JOIN favoritos f ON f.hash = c.hash
            ORDER BY CASE WHEN c.data_fim IS NULL OR c.data_fim = '' THEN 1 ELSE 0 END,
                     c.data_fim ASC
            """
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def favoritos_para_avisar(dias):
    # Favoritos cujo prazo encerra dentro de N dias e que ainda nao foram
    # avisados hoje. Usado para o lembrete de prazo via ntfy.
    hoje = datetime.now().date().isoformat()
    from datetime import timedelta
    limite = (datetime.now().date() + timedelta(days=int(dias))).isoformat()
    conn = conectar()
    try:
        cur = conn.execute(
            """
            SELECT c.* FROM concursos c
            JOIN favoritos f ON f.hash = c.hash
            WHERE c.data_fim >= ? AND c.data_fim <= ?
              AND (f.prazo_avisado IS NULL OR f.prazo_avisado <> ?)
            """,
            (hoje, limite, hoje),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def marcar_prazo_avisado(hash_):
    # Marca que o aviso de prazo deste favorito ja foi enviado hoje.
    conn = conectar()
    try:
        conn.execute(
            "UPDATE favoritos SET prazo_avisado = ? WHERE hash = ?",
            (datetime.now().date().isoformat(), hash_),
        )
        conn.commit()
    finally:
        conn.close()


def set_meta(chave, valor):
    # Grava (ou atualiza) um par chave/valor na tabela meta.
    conn = conectar()
    try:
        conn.execute(
            """
            INSERT INTO meta (chave, valor) VALUES (?, ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
            """,
            (chave, str(valor)),
        )
        conn.commit()
    finally:
        conn.close()


def get_meta(chave):
    # Le um valor da tabela meta. Retorna None se nao existir.
    conn = conectar()
    try:
        cur = conn.execute("SELECT valor FROM meta WHERE chave = ?", (chave,))
        row = cur.fetchone()
        return row["valor"] if row else None
    finally:
        conn.close()


def fazer_backup(max_manter=15):
    # Faz um backup CONSISTENTE do SQLite (via API de backup, segura mesmo com o
    # WAL ativo) numa pasta "backups" ao lado do banco, e mantem apenas os N
    # mais recentes -- importante porque o banco roda num cartao SD no Pi.
    base_dir = os.path.dirname(os.path.abspath(DB_PATH)) or "."
    dir_bkp = os.path.join(base_dir, "backups")
    os.makedirs(dir_bkp, exist_ok=True)
    destino = os.path.join(
        dir_bkp, datetime.now().strftime("concursos-%Y%m%d-%H%M%S-%f.db"))

    origem = conectar()
    try:
        dst = sqlite3.connect(destino)
        try:
            origem.backup(dst)
        finally:
            dst.close()
    finally:
        origem.close()

    # Rotaciona: remove os mais antigos que ultrapassarem o limite.
    removidos = 0
    if max_manter and max_manter > 0:
        arquivos = sorted(glob.glob(os.path.join(dir_bkp, "concursos-*.db")))
        for antigo in arquivos[:-max_manter]:
            try:
                os.remove(antigo)
                removidos += 1
            except OSError:
                pass
    print(f"[backup] {os.path.basename(destino)} criado; "
          f"{removidos} antigo(s) removido(s) (limite {max_manter})")
    return destino
