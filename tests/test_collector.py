"""Testes das funcoes puras de parsing/normalizacao (app/collector.py).

Sao testes sem rede: exercitam apenas o parsing do HTML e a extracao de datas,
que e a parte mais fragil (depende do formato dos sites de origem).
"""

from app import collector


def test_chave_normaliza_orgao_e_inclui_data():
    chave = collector._chave("Prefeitura de Maraba", "pa", "2026-07-10")
    assert chave == "prefeitura maraba|pa|2026-07-10"


def test_limpa_decodifica_entidades_html():
    # Entidades numericas e nomeadas devem virar os caracteres reais, senao o
    # titulo aparece "bugado" (ex: d&#039;Agua) na tela.
    assert collector._limpa("Pref. de M&#227;e d&#039;&#193;gua") == "Pref. de Mãe d'Água"
    assert collector._limpa("Sa&uacute;de &amp; Educa&ccedil;&atilde;o") == "Saúde & Educação"


def test_entidades_geram_mesma_chave_entre_fontes():
    # Regressao do bug de duplicacao: uma fonte traz "&#039;" e a outra "'".
    # Apos decodificar, a chave de dedup tem de ser identica.
    cnb = collector._limpa("C&#226;mara de M&#227;e d&#039;&#193;gua")
    pci = "Câmara de Mãe d'Água - PB"
    assert (collector._chave(cnb, "pb", "2026-06-28")
            == collector._chave(pci, "pb", "2026-06-28"))


def test_chave_vazia_sem_data_fim():
    # Sem data de encerramento, a chave fica vazia (nao funde com ninguem).
    assert collector._chave("Prefeitura de Maraba", "pa", "") == ""


def test_chave_pci_e_cnb_convergem():
    # O mesmo orgao nomeado de formas diferentes nas duas fontes deve gerar a
    # MESMA chave, para a deduplicacao casar.
    cnb = collector._chave("Prefeitura de Maraba", "pa", "2026-07-10")
    pci = collector._chave("Pref. Maraba - PA", "pa", "2026-07-10")
    assert cnb == pci


def test_parse_linha_extrai_campos():
    row = (
        '<tr>'
        '<td><a href="/concursos/pa/2026/06/01/prefeitura-de-belem/" '
        'title="Prefeitura de Belem abre 100 vagas">Prefeitura de Belem</a></td>'
        '<td>100 vagas</td>'
        '</tr>'
    )
    item = collector.parse_linha(row, "pa", "aberto")
    assert item is not None
    assert item["orgao"] == "Prefeitura de Belem"
    assert item["uf"] == "pa"
    assert item["data"] == "2026-06-01"
    assert item["vagas"] == "100 vagas"
    assert item["tipo"] == "aberto"


def test_parse_linha_ignora_link_sem_data():
    # Links de menu/navegacao (sem data no caminho) nao sao concursos.
    row = '<tr><td><a href="/concursos/pa/">Concursos PA</a></td></tr>'
    assert collector.parse_linha(row, "pa", "aberto") is None


def test_extrair_periodo_inicio_e_fim():
    texto = ("As inscricoes vao de 10 de junho de 2026 a 20 de julho de 2026 "
             "pelo site oficial.")
    inicio, fim = collector._extrair_periodo(texto)
    assert inicio == "2026-06-10"
    assert fim == "2026-07-20"


def test_extrair_periodo_so_uma_data_vira_encerramento():
    texto = "Inscricoes ate 15 de agosto de 2026."
    inicio, fim = collector._extrair_periodo(texto)
    assert inicio == ""
    assert fim == "2026-08-15"


def test_para_linha_db_monta_blob_sem_acento():
    item = {
        "orgao": "Secretaria de Educacao",
        "titulo": "Professor de Matematica",
        "vagas": "5 vagas", "link": "https://exemplo/x",
        "uf": "pa", "data": "2026-06-01", "tipo": "aberto",
    }
    linha = collector._para_linha_db(item)
    assert "professor" in linha["blob"]
    assert linha["fonte"] == "Concursos no Brasil"
    # O blob nao deve conter pontuacao nem letras maiusculas.
    assert linha["blob"] == linha["blob"].lower()


def test_ia_desligada_sem_chave(monkeypatch):
    # Sem chave no perfil nem no ambiente, a IA fica desligada (None).
    monkeypatch.setattr(collector, "carregar_perfil", lambda: {})
    monkeypatch.delenv("IA_KEY", raising=False)
    assert collector._config_ia() is None


def test_ia_config_le_chave_do_perfil(monkeypatch):
    monkeypatch.setattr(collector, "carregar_perfil",
                        lambda: {"ia_key": "gsk_teste", "ia_model": "modelo-x"})
    cfg = collector._config_ia()
    assert cfg["key"] == "gsk_teste"
    assert cfg["modelo"] == "modelo-x"
    assert "groq.com" in cfg["url"]


def test_gerar_resumo_ia_formata_saida(monkeypatch):
    # Com a resposta do modelo simulada, monta ia_resumo e ia_estudo.
    monkeypatch.setattr(collector, "_chamar_ia", lambda cfg, texto: {
        "resumo": "Concurso de TI com 10 vagas.",
        "plano_estudo": ["Redes", "Banco de Dados", "Seguranca"],
    })
    out = collector.gerar_resumo_ia({"modelo": "x"}, "texto do edital")
    assert out["ia_resumo"] == "Concurso de TI com 10 vagas."
    assert "Redes" in out["ia_estudo"] and "•" in out["ia_estudo"]


def test_gerar_resumo_ia_none_quando_modelo_falha(monkeypatch):
    monkeypatch.setattr(collector, "_chamar_ia", lambda cfg, texto: None)
    assert collector.gerar_resumo_ia({"modelo": "x"}, "texto") is None


def test_data_prova_iso():
    assert collector.data_prova_iso("15 de agosto de 2026") == "2026-08-15"
    assert collector.data_prova_iso("Prova em 3 de marco de 2027") == "2027-03-03"
    assert collector.data_prova_iso("sem data aqui") == ""


def test_slug_para_busca_de_provas():
    assert collector._slug("Agente Administrativo") == "agente-administrativo"
    assert collector._slug("Tecnico de Enfermagem") == "tecnico-de-enfermagem"


def test_foco_regional_norte_nordeste_e_go():
    # Norte/Nordeste/GO e nacionais entram; outros estados ficam de fora.
    assert collector._no_foco("pa") is True   # Norte
    assert collector._no_foco("ce") is True   # Nordeste
    assert collector._no_foco("go") is True   # extra pedido
    assert collector._no_foco("br") is True   # nacional/federal
    assert collector._no_foco("sp") is False  # fora do foco
    assert collector._no_foco("rs") is False


def test_extrair_salario_faixa_ate_e_unico():
    assert collector._extrair_salario(
        "Salario de R$ 1.500,00 a R$ 8.000,00.") == "R$ 1.500,00 a R$ 8.000,00"
    assert collector._extrair_salario(
        "Remuneracao de ate R$ 5.000,00.") == "ate R$ 5.000,00"
    assert collector._extrair_salario(
        "Vencimento de R$ 3.200,00 mensais.") == "R$ 3.200,00"
    assert collector._extrair_salario("Sem valor informado aqui.") == ""


def test_extrair_detalhes_rico():
    corpo = ("A Prefeitura abre concurso com 50 vagas e cadastro de reserva. "
             "Exige nivel medio e superior. Salarios de R$ 1.500,00 a R$ 8.000,00. "
             "Taxa de inscricao de R$ 80,00. Prova em 15 de agosto de 2026. "
             "Vaga para Analista de Sistemas. Jornada de 40 horas semanais. "
             "Organizadora: FADESP.")
    d = collector._extrair_detalhes(corpo)
    assert d["vagas"] == "50"
    assert d["cadastro_reserva"] == "sim"
    assert d["salario"] == "R$ 1.500,00 a R$ 8.000,00"
    assert d["taxa"] == "R$ 80,00"
    assert d["jornada"] == "40h semanais"
    assert d["banca"] == "FADESP"
    assert "Analista De Sistemas" in d["cargos_ti"]
    assert "Superior" in d["escolaridade"]


def test_extrair_resumo_pega_abertura():
    paragrafos = [
        "Compartilhe:",  # ruido curto, ignorado
        ("A Prefeitura de Belem divulgou edital de concurso publico com 100 "
         "vagas para diversos cargos, com inscricoes abertas em junho."),
    ]
    resumo = collector._extrair_resumo(paragrafos)
    assert resumo.startswith("A Prefeitura de Belem")


def test_cargos_ti_vazio_quando_nao_ha():
    corpo = "Concurso para Professor e Merendeira, nivel medio."
    d = collector._extrair_detalhes(corpo)
    assert "cargos_ti" not in d


def test_conteudo_ti_o_que_cai():
    texto = ("Conteudo: Redes de Computadores, Banco de Dados (SQL), "
             "Seguranca da Informacao e Engenharia de Software.")
    topicos = collector._extrair_conteudo_ti(texto.lower())
    assert "Redes de Computadores" in topicos
    assert "Banco de Dados" in topicos
    assert "Seguranca da Informacao" in topicos
    assert "Engenharia de Software" in topicos


def test_detalhes_inclui_conteudo_ti_quando_ha_vaga_ti():
    corpo = ("Concurso com vaga para Analista de Sistemas. Conteudo programatico: "
             "Banco de Dados, Redes de Computadores e Governanca de TI (ITIL).")
    d = collector._extrair_detalhes(corpo)
    assert "cargos_ti" in d
    assert "conteudo_ti" in d
    assert "Banco de Dados" in d["conteudo_ti"]


def test_sem_conteudo_ti_quando_nao_e_ti():
    # Sem cargo de TI, nao sugere conteudo de TI (evita ruido).
    corpo = "Concurso para Medico. Conteudo: Banco de Dados de pacientes."
    d = collector._extrair_detalhes(corpo)
    assert "conteudo_ti" not in d


def test_regiao_artigo_isola_o_corpo():
    html = ("<header><a href='http://x'>menu</a></header>"
            "<article><p>conteudo da materia</p></article>"
            "<footer>rodape</footer>")
    reg = collector._regiao_artigo(html)
    assert "conteudo da materia" in reg
    assert "menu" not in reg and "rodape" not in reg


def test_oficial_ignora_legislacao_e_pega_gov():
    html = (
        '<article><p>Veja a '
        '<a href="https://www.planalto.gov.br/ccivil_03/lei/L8112.htm">Lei 8.112</a>. '
        'As inscricoes pelo '
        '<a href="https://sead.ma.gov.br/concursos">site oficial</a>.</p></article>'
    )
    oficial, edital = collector._achar_oficial_e_edital(html, "concursosnobrasil")
    assert oficial == "https://sead.ma.gov.br/concursos"
    assert edital == ""


def test_edital_pdf_detectado_no_artigo():
    html = ('<article><p>Confira o '
            '<a href="https://orgao.gov.br/edital-001-2026.pdf">Edital 001/2026</a>.'
            '</p></article>')
    _oficial, edital = collector._achar_oficial_e_edital(html, "concursosnobrasil")
    assert edital.endswith("edital-001-2026.pdf")


def test_links_fora_do_artigo_sao_ignorados():
    html = ('<nav><a href="https://banca.gov.br/concursos">nav</a></nav>'
            '<article><p>Sem links externos aqui.</p></article>')
    oficial, edital = collector._achar_oficial_e_edital(html, "concursosnobrasil")
    assert oficial == "" and edital == ""


def test_link_da_propria_fonte_nao_e_oficial():
    html = ('<article><p>'
            '<a href="https://concursosnobrasil.com/concursos/pa/">veja</a>'
            '</p></article>')
    oficial, _edital = collector._achar_oficial_e_edital(html, "concursosnobrasil")
    assert oficial == ""


def test_extrair_resumo_ignora_menu_do_site():
    # O menu/rodape do site ("Buscar no site... concursos abertos...") nao pode
    # virar resumo; deve ser pulado e o paragrafo real escolhido.
    paragrafos = [
        ("Concursos no Brasil concursos abertos concursos previstos novos "
         "questoes Buscar no site Buscar NACIONAL AC AL AM AP BA CE DF ES GO"),
        ("A SESPA divulgou edital de concurso publico com 127 vagas para a "
         "area da saude no Para, com inscricoes em junho de 2026."),
    ]
    resumo = collector._extrair_resumo(paragrafos)
    assert resumo.startswith("A SESPA divulgou")
