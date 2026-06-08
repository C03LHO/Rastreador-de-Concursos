# Mapa de areas para palavras-chave.
#
# Ao filtrar por uma area (ex: "ti"), o app procura QUALQUER uma das palavras
# da lista dentro do campo blob de cada concurso. Por isso vale a pena incluir
# variacoes com e sem acento, no singular e no plural.
#
# Este arquivo foi pensado para ser editado a vontade: para criar uma area nova
# basta adicionar uma chave com a sua lista de palavras.

AREAS = {
    "ti": [
        "ti", "informatica", "informática", "sistemas", "dados",
        "desenvolvedor", "programador", "redes", "suporte tecnico",
        "suporte técnico", "software", "tecnologia da informacao",
        "tecnologia da informação", "analista de sistemas",
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
