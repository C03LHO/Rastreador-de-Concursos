"""Testes da camada de banco (app/db.py)."""

from datetime import date, timedelta

from tests.conftest import item_listagem


def _chave_de(banco, hash_):
    conn = banco.conectar()
    try:
        return conn.execute(
            "SELECT chave FROM concursos WHERE hash = ?", (hash_,)
        ).fetchone()["chave"]
    finally:
        conn.close()


def test_upsert_novo_depois_atualiza(banco):
    # Primeira vez e novo (True); segunda vez e atualizacao (False).
    assert banco.upsert_concurso(item_listagem("h1")) is True
    assert banco.upsert_concurso(item_listagem("h1", vagas="20 vagas")) is False
    assert banco.contar_total() == 1


def test_chave_de_dedup_preservada_na_coleta_horaria(banco):
    # Regressao do bug: a coleta horaria (chave vazia) nao pode apagar a chave
    # que o enriquecimento ja calculou.
    banco.upsert_concurso(item_listagem("h1", chave=""))
    banco.atualizar_detalhe("h1", {"data_fim": "2030-07-10",
                                   "chave": "maraba|pa|2030-07-10"})
    assert _chave_de(banco, "h1") == "maraba|pa|2030-07-10"

    # Coleta horaria roda de novo com chave vazia: a chave deve permanecer.
    banco.upsert_concurso(item_listagem("h1", chave=""))
    assert _chave_de(banco, "h1") == "maraba|pa|2030-07-10"


def test_filtro_por_uf(banco):
    banco.upsert_concurso(item_listagem("h1", uf="pa"))
    banco.upsert_concurso(item_listagem("h2", uf="sp", link="https://exemplo/h2"))
    resultado = banco.buscar_concursos(uf="pa")
    assert [c["hash"] for c in resultado] == ["h1"]


def test_esconde_encerrados_por_padrao(banco):
    ontem = (date.today() - timedelta(days=1)).isoformat()
    amanha = (date.today() + timedelta(days=30)).isoformat()
    banco.upsert_concurso(item_listagem("aberto"))
    banco.atualizar_detalhe("aberto", {"data_fim": amanha})
    banco.upsert_concurso(item_listagem("encerrado", link="https://exemplo/e"))
    banco.atualizar_detalhe("encerrado", {"data_fim": ontem})

    hashes = {c["hash"] for c in banco.buscar_concursos()}
    assert hashes == {"aberto"}

    # Com incluir_encerrados, os dois aparecem.
    hashes_todos = {c["hash"] for c in banco.buscar_concursos(incluir_encerrados=True)}
    assert hashes_todos == {"aberto", "encerrado"}


def test_area_casa_por_palavra_inteira(banco):
    # "ti" como area NAO pode casar dentro de "tocantins".
    banco.upsert_concurso(item_listagem(
        "ti", blob="analista de ti sistemas", orgao="Orgao TI"))
    banco.upsert_concurso(item_listagem(
        "tocantins", link="https://exemplo/to",
        blob="governo do tocantins professor", orgao="Governo do Tocantins"))

    achados = {c["hash"] for c in banco.buscar_concursos(area_palavras=["ti"])}
    assert achados == {"ti"}


def test_dedup_entre_fontes_esconde_pci(banco):
    # Mesmo concurso em duas fontes (mesma chave): so o "Concursos no Brasil"
    # (preferido) aparece; o do PCI fica escondido.
    futuro = (date.today() + timedelta(days=20)).isoformat()
    chave = f"maraba|pa|{futuro}"
    banco.upsert_concurso(item_listagem(
        "cnb", fonte="Concursos no Brasil", chave=chave,
        link="https://exemplo/cnb"))
    banco.atualizar_detalhe("cnb", {"data_fim": futuro})
    banco.upsert_concurso(item_listagem(
        "pci", fonte="PCI Concursos", chave=chave, link="https://exemplo/pci"))
    banco.atualizar_detalhe("pci", {"data_fim": futuro})

    hashes = {c["hash"] for c in banco.buscar_concursos()}
    assert hashes == {"cnb"}


def test_favoritos_alternar_e_listar(banco):
    futuro = (date.today() + timedelta(days=5)).isoformat()
    mais_futuro = (date.today() + timedelta(days=40)).isoformat()
    banco.upsert_concurso(item_listagem("cedo", link="https://exemplo/cedo"))
    banco.atualizar_detalhe("cedo", {"data_fim": futuro})
    banco.upsert_concurso(item_listagem("tarde", link="https://exemplo/tarde"))
    banco.atualizar_detalhe("tarde", {"data_fim": mais_futuro})

    assert banco.alternar_favorito("cedo") is True
    assert banco.alternar_favorito("tarde") is True
    assert set(banco.hashes_favoritos()) == {"cedo", "tarde"}

    # Listagem ordenada por prazo: o que encerra antes vem primeiro.
    ordem = [c["hash"] for c in banco.listar_favoritos()]
    assert ordem == ["cedo", "tarde"]

    # Desfavoritar volta False e some da lista.
    assert banco.alternar_favorito("cedo") is False
    assert set(banco.hashes_favoritos()) == {"tarde"}


def test_concursos_para_ia_e_merge(banco):
    import json
    # Item de TI ja enriquecido, ainda sem resumo de IA -> entra na fila.
    banco.upsert_concurso(item_listagem("ti1"))
    banco.atualizar_detalhe("ti1", {
        "data_fim": "2030-01-01", "blob_detalhe": "texto do edital de ti",
        "detalhes_json": json.dumps({"cargos_ti": "Programador"}),
    })
    # Item sem TI -> NAO entra.
    banco.upsert_concurso(item_listagem("x1", link="https://exemplo/x1"))
    banco.atualizar_detalhe("x1", {"data_fim": "2030-01-01",
                                   "detalhes_json": json.dumps({"banca": "FGV"})})

    fila = banco.concursos_para_ia(10)
    assert [c["hash"] for c in fila] == ["ti1"]

    # Apos gravar o resumo de IA, sai da fila e o detalhe e mesclado.
    banco.adicionar_detalhes_ia("ti1", {"ia_resumo": "Resumo.", "ia_estudo": "Redes"})
    assert banco.concursos_para_ia(10) == []
    c = banco.get_concurso("ti1")
    det = json.loads(c["detalhes_json"])
    assert det["cargos_ti"] == "Programador"  # preservado
    assert det["ia_resumo"] == "Resumo."       # adicionado


def test_backup_cria_e_rotaciona(banco):
    import os, glob
    banco.upsert_concurso(item_listagem("h1"))
    # Faz 18 backups mantendo no maximo 15 -> sobram 15.
    for _ in range(18):
        banco.fazer_backup(max_manter=15)
    dir_bkp = os.path.join(os.path.dirname(os.path.abspath(banco.DB_PATH)), "backups")
    arquivos = glob.glob(os.path.join(dir_bkp, "concursos-*.db"))
    assert len(arquivos) == 15
    # O backup e um SQLite valido com os dados.
    import sqlite3
    mais_novo = sorted(arquivos)[-1]
    conn = sqlite3.connect(mais_novo)
    try:
        n = conn.execute("SELECT COUNT(*) FROM concursos").fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_meta_grava_e_le(banco):
    assert banco.get_meta("inexistente") is None
    banco.set_meta("ultima_coleta", "2026-06-28T10:00:00")
    assert banco.get_meta("ultima_coleta") == "2026-06-28T10:00:00"
