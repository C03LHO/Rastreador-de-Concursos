"""Camada de acesso ao banco SQLite.

Aqui ficam a criacao das tabelas, o upsert dos concursos, a busca com filtros
e o controle dos metadados de coleta (ultima_coleta e ultimo_resultado).

Cada operacao abre e fecha a sua propria conexao. Isso e simples e seguro para
o uso simultaneo entre as threads do scheduler e as requisicoes da API.
"""

import os
import sqlite3
import unicodedata
from datetime import datetime

# Caminho do arquivo do banco. Em Docker apontamos para /data/concursos.db via
# variavel de ambiente para o arquivo ficar no volume persistido.
DB_PATH = os.environ.get("DB_PATH", "concursos.db")

# Marca do modelo de dados / fonte atual. Se mudar, os dados antigos (por
# exemplo, os da API anterior, que nao tinham link) sao limpos no boot.
VERSAO_FONTE = "concursosnobrasil-v2"


def remover_acentos(texto):
    # Remove acentos para a busca ser insensivel a eles (ex: "saude" acha
    # "saude" e "saude"). Usado tanto no blob gravado quanto nos termos de busca.
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def conectar():
    # Abre uma conexao nova. row_factory deixa as linhas acessiveis por nome.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def iniciar_banco():
    # Cria as tabelas caso ainda nao existam e aplica migracoes simples.
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

        # Migracao: adiciona colunas novas em bancos criados em versoes antigas.
        existentes = {r["name"] for r in conn.execute("PRAGMA table_info(concursos)")}
        novas = (
            "titulo", "data", "data_inicio", "data_fim", "link_oficial",
            "pdf_url", "resumo", "detalhes_json", "blob_detalhe", "detalhe_em",
        )
        for coluna in novas:
            if coluna not in existentes:
                conn.execute(f"ALTER TABLE concursos ADD COLUMN {coluna} TEXT")

        # Indices simples para acelerar os filtros mais comuns.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_concursos_uf ON concursos(uf)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_concursos_tipo ON concursos(tipo)")

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
            conn.execute(
                """
                UPDATE concursos
                SET uf = ?, orgao = ?, titulo = ?, situacao = ?, link = ?,
                    vagas = ?, tipo = ?, data = ?, blob = ?, raw_json = ?,
                    atualizado_em = ?
                WHERE hash = ?
                """,
                (
                    item["uf"], item["orgao"], item["titulo"], item["situacao"],
                    item["link"], item["vagas"], item["tipo"], item["data"],
                    item["blob"], item["raw_json"], agora, item["hash"],
                ),
            )
        else:
            # Novo: insere e marca primeira_vez igual a atualizado_em.
            conn.execute(
                """
                INSERT INTO concursos
                    (hash, uf, orgao, titulo, situacao, link, vagas, tipo, data,
                     blob, raw_json, primeira_vez, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["hash"], item["uf"], item["orgao"], item["titulo"],
                    item["situacao"], item["link"], item["vagas"], item["tipo"],
                    item["data"], item["blob"], item["raw_json"], agora, agora,
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
            SELECT hash, link, uf, tipo FROM concursos
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


def atualizar_detalhe(hash_, dados):
    # Grava os campos extraidos da pagina de detalhe e do PDF do edital.
    conn = conectar()
    try:
        agora = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            UPDATE concursos
            SET data_inicio = ?, data_fim = ?, link_oficial = ?, pdf_url = ?,
                resumo = ?, detalhes_json = ?, blob_detalhe = ?, detalhe_em = ?
            WHERE hash = ?
            """,
            (
                dados.get("data_inicio", ""), dados.get("data_fim", ""),
                dados.get("link_oficial", ""), dados.get("pdf_url", ""),
                dados.get("resumo", ""), dados.get("detalhes_json", ""),
                dados.get("blob_detalhe", ""), agora, hash_,
            ),
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
                     tipo=None, q=None, limite=100):
    # Monta a consulta dinamicamente. Todos os filtros sao combinados em E.
    clausulas = []
    params = []

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

    sql = "SELECT * FROM concursos"
    if clausulas:
        sql += " WHERE " + " AND ".join(clausulas)
    # Mostra primeiro os mais recentes (pela data de publicacao) e limita.
    sql += " ORDER BY data DESC, atualizado_em DESC LIMIT ?"
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
