# Mapa de areas para palavras-chave.
#
# Ao filtrar por uma area (ex: "ti"), o app procura QUALQUER uma das palavras
# da lista dentro do campo blob de cada concurso. Por isso vale a pena incluir
# variacoes com e sem acento, no singular e no plural.
#
# Este arquivo foi pensado para ser editado a vontade: para criar uma area nova
# basta adicionar uma chave com a sua lista de palavras.

AREAS = {
    # TI e o foco principal: lista ampla, cobrindo todas as subareas de
    # tecnologia (a busca casa por palavra inteira, entao termos curtos como
    # "ti" nao casam dentro de "tocantins"). Sem acento ja basta (a busca
    # ignora acentos), mas mantemos algumas variantes por clareza.
    "ti": [
        # Termos guarda-chuva
        "ti", "tic", "informatica", "informática", "computacao", "computação",
        "tecnologia da informacao", "tecnologia da informação",
        "tecnologia da informacao e comunicacao",
        # Cargos de analista
        "analista de sistemas", "analista de ti",
        "analista de tecnologia da informacao", "analista de tecnologia",
        "analista de suporte", "analista de infraestrutura",
        "analista de redes", "analista de banco de dados", "analista de dados",
        "analista de seguranca da informacao", "analista de desenvolvimento",
        # Desenvolvimento / software
        "desenvolvedor", "desenvolvimento de sistemas", "desenvolvimento de software",
        "programador", "programacao", "programação", "software",
        "engenheiro de software", "engenharia de software",
        "engenharia da computacao", "engenharia de computacao",
        "engenheiro da computacao", "web", "mobile", "front-end", "back-end",
        "fullstack", "full stack",
        # Infraestrutura, redes e suporte
        "redes", "redes de computadores", "infraestrutura",
        "administrador de redes", "administrador de sistemas",
        "suporte tecnico", "suporte técnico", "suporte de ti",
        "help desk", "helpdesk", "service desk", "manutencao de computadores",
        # Dados e BI
        "banco de dados", "dados", "dba", "administrador de banco de dados",
        "ciencia de dados", "cientista de dados", "analista de bi",
        "business intelligence", "big data",
        # Seguranca e tendencias
        "seguranca da informacao", "segurança da informação",
        "ciberseguranca", "cibersegurança", "seguranca cibernetica",
        "devops", "cloud", "computacao em nuvem",
        "governanca de ti", "governança de ti", "governanca de tecnologia",
        # Sistemas de informacao e tecnologos / tecnicos
        "sistemas de informacao", "sistemas de informação",
        "tecnologo em sistemas", "tecnologo em ti",
        "tecnico em informatica", "técnico em informática",
        "tecnico de informatica", "tecnico em ti", "tecnico em redes",
        "tecnico em manutencao", "operador de computador",
    ],
    "saude": [
        "saude", "saúde", "medico", "médico", "medicina", "enfermeiro",
        "enfermeira", "enfermagem", "odontologo", "odontólogo", "dentista",
        "farmaceutico", "farmacêutico", "psicologo", "psicólogo",
        "fisioterapeuta", "tecnico de enfermagem", "técnico de enfermagem",
        "hospital", "samu", "agente de saude", "agente de saúde",
    ],
    "educacao": [
        "educacao", "educação", "professor", "professora", "docente",
        "magisterio", "magistério", "pedagogo", "pedagoga", "pedagogia",
        "escola", "ensino", "merendeira", "secretaria de educacao",
        "secretaria de educação",
    ],
    "juridico": [
        "juridico", "jurídico", "advogado", "advogada", "procurador",
        "procuradoria", "promotor", "juiz", "defensor", "defensoria",
        "analista judiciario", "analista judiciário", "tecnico judiciario",
        "técnico judiciário", "direito", "oficial de justica",
        "oficial de justiça",
    ],
    "administrativo": [
        "administrativo", "administracao", "administração",
        "assistente administrativo", "auxiliar administrativo",
        "agente administrativo", "secretario", "secretário",
        "recepcionista", "gestao", "gestão", "auxiliar de servicos",
        "auxiliar de serviços",
    ],
    "engenharia": [
        "engenharia", "engenheiro", "engenheira", "arquiteto", "arquiteta",
        "tecnico em edificacoes", "técnico em edificações", "agrimensor",
        "engenharia civil", "engenharia eletrica", "engenharia elétrica",
        "engenharia ambiental",
    ],
    "seguranca": [
        "seguranca", "segurança", "policial", "policia", "polícia",
        "guarda", "guarda municipal", "bombeiro", "penitenciario",
        "penitenciário", "agente penitenciario", "agente penitenciário",
        "vigilante", "militar", "soldado", "delegado", "perito",
    ],
    "fiscal_financeiro": [
        "fiscal", "auditor", "auditoria", "contador", "contabilidade",
        "economista", "economia", "financeiro", "tesouraria", "tributario",
        "tributário", "receita", "analista fiscal", "fiscal de tributos",
    ],
}
