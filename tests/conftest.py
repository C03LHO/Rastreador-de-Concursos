"""Configuracao comum dos testes.

Cada teste roda contra um banco SQLite temporario e isolado, criado do zero.
Como db.conectar() le db.DB_PATH a cada chamada, basta apontar essa variavel
para um arquivo novo em uma pasta temporaria do pytest.
"""

import pytest

from app import db as _db


@pytest.fixture
def banco(tmp_path, monkeypatch):
    # Aponta o banco para um arquivo temporario exclusivo do teste e cria as
    # tabelas. Nada vaza entre os testes nem para o banco real.
    caminho = tmp_path / "teste.db"
    monkeypatch.setattr(_db, "DB_PATH", str(caminho))
    _db.iniciar_banco()
    return _db


def item_listagem(hash_, **over):
    # Monta um item ja no formato gravado por upsert_concurso (campos da
    # listagem). Os testes sobrescrevem o que precisarem via **over.
    base = {
        "hash": hash_,
        "uf": "pa",
        "orgao": "Prefeitura de Maraba",
        "titulo": "Edital 01/2026",
        "situacao": "Inscricoes abertas",
        "link": f"https://exemplo/{hash_}",
        "vagas": "10 vagas",
        "tipo": "aberto",
        "data": "2026-06-01",
        "fonte": "Concursos no Brasil",
        "chave": "",
        "blob": "prefeitura de maraba edital analista",
        "raw_json": "{}",
    }
    base.update(over)
    return base
