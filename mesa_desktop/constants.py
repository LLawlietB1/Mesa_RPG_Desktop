"""Listas de opções (chave, rótulo). Idênticas às do app web para que os dois leiam os mesmos valores."""

CAMPAIGN_STATUS = [("planejada", "Planejada"), ("ativa", "Ativa"), ("pausada", "Pausada"), ("encerrada", "Encerrada")]
PLAYER_STATUS = [("ativo", "Ativo"), ("inativo", "Inativo"), ("arquivado", "Arquivado")]
CHARACTER_STATUS = [("ativo", "Ativo"), ("afastado", "Afastado"), ("aposentado", "Aposentado"), ("morto", "Morto")]
SESSION_STATUS = [("agendada", "Agendada"), ("realizada", "Realizada"), ("cancelada", "Cancelada")]
NPC_STATUS = [("ativo", "Ativo"), ("morto", "Morto"), ("desaparecido", "Desaparecido"), ("desconhecido", "Indefinido")]
NPC_RELATIONS = [
    ("alianca", "Aliança"), ("rivalidade", "Rivalidade"), ("amizade", "Amizade"), ("familiar", "Familiar"),
    ("mentor", "Mentoria"), ("divida", "Dívida"), ("neutro", "Neutro"), ("outro", "Outro"),
]
QUEST_STATUS = [
    ("planejada", "Planejada"), ("disponivel", "Disponível"), ("em_andamento", "Em andamento"),
    ("concluida", "Concluída"), ("fracassada", "Fracassada"), ("abandonada", "Abandonada"),
]
ITEM_CATEGORIES = [
    ("moeda", "Moeda"), ("tesouro", "Tesouro"), ("equipamento", "Equipamento"),
    ("item_especial", "Item especial"), ("consumivel", "Consumível"), ("outro", "Outro"),
]
NOTE_CATEGORIES = [
    ("jogador", "Observação sobre o jogador"), ("personagem", "Informação sobre o personagem"),
    ("segredo", "Segredo narrativo"), ("gancho", "Gancho para sessão futura"),
    ("npc", "Relacionamento com NPC"), ("consequencia", "Consequência de uma decisão"),
    ("ideia", "Ideia para a campanha"), ("outros", "Outros"),
]
XP_ORIGINS = [
    ("individual", "Individual"), ("coletiva", "Coletiva"), ("novo_ciclo", "Novo ciclo"),
]

ALL_CHOICES = {
    "campaign_status": CAMPAIGN_STATUS, "player_status": PLAYER_STATUS, "character_status": CHARACTER_STATUS,
    "session_status": SESSION_STATUS, "npc_status": NPC_STATUS, "npc_relations": NPC_RELATIONS,
    "quest_status": QUEST_STATUS, "item_categories": ITEM_CATEGORIES, "note_categories": NOTE_CATEGORIES,
    "xp_origins": XP_ORIGINS,
}


def keys(choices):
    return [k for k, _ in choices]


def label(choices, key):
    return dict(choices).get(key, key or "")


def in_clause(column, choices):
    """Texto de CHECK constraint: coluna IN ('a','b',...)."""
    return f"{column} IN ({', '.join(repr(k) for k in keys(choices))})"
