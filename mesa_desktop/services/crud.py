"""Operações de cadastro (criar/editar/excluir) com as mesmas validações e regras do app web.

Toda função recebe a sessão do banco `s` e o id do usuário `uid`; nada aqui conhece a interface. Erros de regra
de negócio viram `AppError` com mensagem pronta para exibir."""
from __future__ import annotations

from datetime import date

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from mesa_desktop import constants as C
from mesa_desktop.models import (NPC, Campaign, CampaignPlayer, Character, CharacterItem, CharacterNPCRelationship,
                                 GameSession, Item, Note, Player, Quest, QuestObjective, QuestStatusHistory,
                                 SessionEvent, User, utcnow)
from mesa_desktop.services import images
from mesa_desktop.services.errors import AppError
from mesa_desktop.services.messaging import PhoneError, normalize_phone
from mesa_desktop.utils import clean, parse_kv_lines


# ---------------------------------------------------------------- validação

def _text(value, label, max_len, required=False) -> str | None:
    value = clean(value)
    if required and not value:
        raise AppError(f"{label}: campo obrigatório.")
    if value and len(value) > max_len:
        raise AppError(f"{label}: use no máximo {max_len} caracteres.")
    return value


def _choice(value, choices, label) -> str:
    if value not in C.keys(choices):
        raise AppError(f"{label}: valor inválido.")
    return value


def _commit(s: Session, what="Não foi possível salvar. Nenhum dado foi alterado."):
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise AppError("Já existe um registro com estes dados.") from None
    except SQLAlchemyError:
        s.rollback()
        raise AppError(what) from None


# ---------------------------------------------------------------- posse / integridade

def campaign_of(s: Session, obj) -> Campaign | None:
    cid = getattr(obj, "campaign_id", None)
    return s.get(Campaign, cid) if cid is not None else None


def owner_id_of(s: Session, obj) -> int | None:
    if isinstance(obj, (Campaign, Player)):
        return obj.owner_id
    if isinstance(obj, QuestObjective | QuestStatusHistory):
        return owner_id_of(s, obj.quest)
    if isinstance(obj, CharacterNPCRelationship):
        return owner_id_of(s, obj.npc)
    if isinstance(obj, CharacterItem):
        return owner_id_of(s, obj.item)
    campaign = campaign_of(s, obj)
    return campaign.owner_id if campaign else None


def get_owned(s: Session, model, ident: int | None, uid: int):
    """Carrega por id e só devolve se for do usuário; senão erro (não revela que existe)."""
    obj = s.get(model, ident) if ident is not None else None
    if obj is None or owner_id_of(s, obj) != uid:
        raise AppError("Registro não encontrado.")
    return obj


def load_in_campaign(s: Session, model, ids, campaign_id: int, what: str):
    ids = list(dict.fromkeys(i for i in ids if i))
    if not ids:
        return []
    rows = s.query(model).filter(model.id.in_(ids)).all()
    if len(rows) != len(ids):
        raise AppError(f"Um ou mais {what} informados não existem.")
    for row in rows:
        if row.campaign_id != campaign_id:
            name = getattr(row, "name", None) or getattr(row, "title", row.id)
            raise AppError(f"«{name}» pertence a outra campanha.")
    return rows


# ---------------------------------------------------------------- campanhas

CAMPAIGN_FIELDS = dict(name=("Nome da campanha", 120, True), system=("Sistema de RPG", 80, False),
                       setting=("Ambientação", 120, False), description=("Descrição", 5000, False),
                       notes=("Observações gerais", 10000, False))


def my_campaigns(s: Session, uid: int, q: str = "", status: str = ""):
    from mesa_desktop.utils import like_pattern
    query = s.query(Campaign).filter_by(owner_id=uid)
    if q.strip():
        query = query.filter(Campaign.name.ilike(like_pattern(q.strip()), escape="\\"))
    if status in C.keys(C.CAMPAIGN_STATUS):
        query = query.filter_by(status=status)
    return query.order_by(Campaign.status == "encerrada", Campaign.name).all()


def save_campaign(s: Session, user: User, data: dict, campaign: Campaign | None = None) -> Campaign:
    """data: name,status,system,setting,start_date(date|None),description,notes,settings_text,
    cover_path(str|None: nova imagem), remove_cover(bool)."""
    values = {k: _text(data.get(k), label, n, req) for k, (label, n, req) in CAMPAIGN_FIELDS.items()}
    status = _choice(data.get("status") or "planejada", C.CAMPAIGN_STATUS, "Status")
    try:
        settings = parse_kv_lines(data.get("settings_text"))
    except ValueError as exc:
        raise AppError(str(exc)) from None
    new = campaign is None
    campaign = campaign or Campaign(owner_id=user.id)
    for k, v in values.items():
        setattr(campaign, k, v)
    campaign.status, campaign.settings, campaign.start_date = status, settings, data.get("start_date")
    _apply_image(s, user, campaign, "cover_image", data.get("cover_path"), data.get("remove_cover"))
    if new:
        s.add(campaign)
    _commit(s)
    return campaign


def set_campaign_status(s: Session, uid: int, campaign: Campaign, status: str) -> None:
    get_owned(s, Campaign, campaign.id, uid)
    campaign.status = _choice(status, C.CAMPAIGN_STATUS, "Status")
    _commit(s)


def delete_campaign(s: Session, uid: int, campaign: Campaign, confirm_name: str) -> None:
    campaign = get_owned(s, Campaign, campaign.id, uid)
    if (confirm_name or "").strip() != campaign.name:
        raise AppError("Para excluir definitivamente, digite o nome exato da campanha.")
    for img in [campaign.cover_image] + [c.portrait for c in campaign.characters] + [n.image for n in campaign.npcs]:
        images.delete_image(s, uid, img)
    s.delete(campaign)
    _commit(s, "Não foi possível excluir a campanha.")


def campaign_members(s: Session, campaign_id: int, only_active=True):
    q = (s.query(Player, CampaignPlayer).join(CampaignPlayer, CampaignPlayer.player_id == Player.id)
         .filter(CampaignPlayer.campaign_id == campaign_id))
    if only_active:
        q = q.filter(CampaignPlayer.status == "ativo")
    return q.order_by(Player.display_name).all()


def enroll_player(s: Session, campaign_id: int, player_id: int) -> CampaignPlayer:
    """Registra (ou reativa) a participação. Não faz commit."""
    campaign, player = s.get(Campaign, campaign_id), s.get(Player, player_id)
    if campaign is None or player is None or campaign.owner_id != player.owner_id:
        raise AppError("Jogador e campanha precisam pertencer à mesma conta.")
    membership = s.query(CampaignPlayer).filter_by(campaign_id=campaign_id, player_id=player_id).first()
    if membership is None:
        membership = CampaignPlayer(campaign_id=campaign_id, player_id=player_id)
        s.add(membership)
    elif membership.status != "ativo":
        membership.status, membership.left_at = "ativo", None
    return membership


def add_player_to_campaign(s: Session, uid: int, campaign_id: int, player_id: int) -> None:
    get_owned(s, Campaign, campaign_id, uid)
    player = get_owned(s, Player, player_id, uid)
    if player.status == "arquivado":
        raise AppError("Jogadores arquivados não podem ser adicionados.")
    enroll_player(s, campaign_id, player_id)
    _commit(s)


def remove_player_from_campaign(s: Session, uid: int, campaign_id: int, player_id: int) -> None:
    get_owned(s, Campaign, campaign_id, uid)
    m = s.query(CampaignPlayer).filter_by(campaign_id=campaign_id, player_id=player_id).first()
    if m is None:
        raise AppError("Participação não encontrada.")
    m.status, m.left_at = "saiu", utcnow()
    _commit(s)


# ---------------------------------------------------------------- imagens

def _apply_image(s: Session, user: User, obj, attr: str, new_path: str | None, remove: bool = False) -> None:
    """Troca/remove a imagem de um campo (sem commit). A antiga é apagada na mesma transação."""
    old = getattr(obj, attr)
    if new_path:
        setattr(obj, attr, images.save_image_from_file(s, user, new_path))
        images.delete_image(s, user.id, old)
    elif remove and old:
        setattr(obj, attr, None)
        images.delete_image(s, user.id, old)


# ---------------------------------------------------------------- jogadores

def my_players(s: Session, uid: int, q: str = "", status: str = "", campaign_id: int | None = None):
    from mesa_desktop.utils import like_pattern
    query = s.query(Player).filter_by(owner_id=uid)
    if q.strip():
        pat = like_pattern(q.strip())
        query = query.filter(Player.display_name.ilike(pat, escape="\\") | Player.nickname.ilike(pat, escape="\\")
                             | Player.real_name.ilike(pat, escape="\\"))
    if status in C.keys(C.PLAYER_STATUS):
        query = query.filter(Player.status == status)
    if campaign_id:
        query = query.join(CampaignPlayer).filter(CampaignPlayer.campaign_id == campaign_id,
                                                  CampaignPlayer.status == "ativo")
    return query.order_by(Player.display_name).all()


def save_player(s: Session, uid: int, data: dict, player: Player | None = None) -> Player:
    name = _text(data.get("display_name"), "Nome de exibição", 120, True)
    email = _text(data.get("email"), "E-mail", 200)
    if email:
        from mesa_desktop.services.auth import check_email
        email = check_email(email)
    phone = _text(data.get("phone"), "Telefone", 30)
    try:
        phone = normalize_phone(phone) if phone else None
    except PhoneError as exc:
        raise AppError(str(exc)) from None
    new = player is None
    player = player or Player(owner_id=uid)
    player.display_name = name
    player.real_name = _text(data.get("real_name"), "Nome real", 120)
    player.nickname = _text(data.get("nickname"), "Apelido", 80)
    player.email, player.phone = email, phone
    player.messaging_consent = bool(data.get("messaging_consent") and phone)
    player.status = _choice(data.get("status") or "ativo", C.PLAYER_STATUS, "Status")
    player.notes = _text(data.get("notes"), "Observações", 5000)
    if new:
        s.add(player)
    _commit(s)
    return player


def set_player_status(s: Session, uid: int, player: Player, status: str) -> None:
    get_owned(s, Player, player.id, uid).status = _choice(status, C.PLAYER_STATUS, "Status")
    _commit(s)


def delete_player(s: Session, uid: int, player: Player) -> None:
    player = get_owned(s, Player, player.id, uid)
    if s.query(Character.id).filter_by(player_id=player.id).first():
        raise AppError("Este jogador possui personagens e não pode ser excluído. Arquive-o para preservar o histórico.")
    s.delete(player)
    _commit(s, "Não foi possível excluir o jogador.")


# ---------------------------------------------------------------- personagens

def campaign_characters(s: Session, campaign_id: int, active_only=False):
    q = s.query(Character).filter_by(campaign_id=campaign_id)
    if active_only:
        q = q.filter(Character.status == "ativo")
    return q.order_by(Character.name).all()


def player_choices(s: Session, uid: int, include_player_id: int | None = None):
    q = s.query(Player).filter_by(owner_id=uid).filter((Player.status != "arquivado") | (Player.id == include_player_id))
    return q.order_by(Player.display_name).all()


def save_character(s: Session, user: User, campaign_id: int, data: dict, character: Character | None = None) -> Character:
    campaign = get_owned(s, Campaign, campaign_id, user.id)
    player = get_owned(s, Player, data.get("player_id"), user.id)
    level = data.get("level")
    if level is not None and not 0 <= int(level) <= 999:
        raise AppError("O nível deve estar entre 0 e 999.")
    try:
        extra = parse_kv_lines(data.get("extra_text"))
    except ValueError as exc:
        raise AppError(str(exc)) from None
    new = character is None
    character = character or Character(campaign_id=campaign.id)
    character.name = _text(data.get("name"), "Nome do personagem", 120, True)
    character.player_id = player.id
    character.status = _choice(data.get("status") or "ativo", C.CHARACTER_STATUS, "Status")
    character.system = _text(data.get("system"), "Sistema", 80)
    character.race = _text(data.get("race"), "Raça", 80)
    character.char_class = _text(data.get("char_class"), "Classe", 80)
    character.level = level
    character.backstory = _text(data.get("backstory"), "História", 10000)
    character.personality = _text(data.get("personality"), "Personalidade", 5000)
    character.goals = _text(data.get("goals"), "Objetivos", 5000)
    character.background = _text(data.get("background"), "Antecedentes", 5000)
    character.master_notes = _text(data.get("master_notes"), "Observações do mestre", 10000)
    character.extra = extra
    _apply_image(s, user, character, "portrait", data.get("portrait_path"), data.get("remove_portrait"))
    if new:
        s.add(character)
    enroll_player(s, campaign.id, player.id)
    _commit(s)
    return character


def set_character_status(s: Session, uid: int, character: Character, status: str) -> None:
    get_owned(s, Character, character.id, uid).status = _choice(status, C.CHARACTER_STATUS, "Status")
    _commit(s)


def delete_character(s: Session, uid: int, character: Character) -> None:
    character = get_owned(s, Character, character.id, uid)
    images.delete_image(s, uid, character.portrait)
    s.delete(character)
    _commit(s, "Não foi possível excluir o personagem.")


# ---------------------------------------------------------------- sessões

def next_session_number(s: Session, campaign_id: int) -> int:
    from sqlalchemy import func
    return (s.query(func.max(GameSession.number)).filter_by(campaign_id=campaign_id).scalar() or 0) + 1


def save_session(s: Session, uid: int, campaign_id: int, data: dict, session: GameSession | None = None) -> GameSession:
    get_owned(s, Campaign, campaign_id, uid)
    number = int(data.get("number") or 0)
    if not 1 <= number <= 9999:
        raise AppError("Use um número de sessão entre 1 e 9999.")
    if not data.get("date"):
        raise AppError("Informe a data da sessão.")
    taken = s.query(GameSession.id).filter_by(campaign_id=campaign_id, number=number)
    if session is not None:
        taken = taken.filter(GameSession.id != session.id)
    if taken.first():
        raise AppError("Já existe uma sessão com este número nesta campanha.")
    new = session is None
    session = session or GameSession(campaign_id=campaign_id)
    session.number = number
    session.title = _text(data.get("title"), "Título", 160, True)
    session.date = data["date"]
    session.status = _choice(data.get("status") or "agendada", C.SESSION_STATUS, "Status")
    session.summary = _text(data.get("summary"), "Resumo", 20000)
    session.pending = _text(data.get("pending"), "Pendências", 10000)
    session.master_notes = _text(data.get("master_notes"), "Observações", 10000)
    session.participants = load_in_campaign(s, Character, data.get("participants") or [], campaign_id, "personagens")
    session.npcs = load_in_campaign(s, NPC, data.get("npcs") or [], campaign_id, "NPCs")
    session.quests = load_in_campaign(s, Quest, data.get("quests") or [], campaign_id, "missões")
    if new:
        s.add(session)
    _commit(s)
    return session


def delete_session(s: Session, uid: int, session: GameSession) -> None:
    s.delete(get_owned(s, GameSession, session.id, uid))
    _commit(s, "Não foi possível excluir a sessão.")


def add_session_event(s: Session, uid: int, session_id: int, description: str, character_id: int | None) -> None:
    session = get_owned(s, GameSession, session_id, uid)
    text = _text(description, "Acontecimento", 2000, True)
    event = SessionEvent(session_id=session.id, campaign_id=session.campaign_id, description=text)
    if character_id:
        (event.character,) = load_in_campaign(s, Character, [character_id], session.campaign_id, "personagens")
    s.add(event)
    _commit(s)


def delete_session_event(s: Session, uid: int, event_id: int) -> None:
    event = s.get(SessionEvent, event_id)
    if event is None or owner_id_of(s, event) != uid:
        raise AppError("Acontecimento não encontrado.")
    s.delete(event)
    _commit(s)


# ---------------------------------------------------------------- notas

def save_note(s: Session, uid: int, campaign_id: int, data: dict, note: Note | None = None) -> Note:
    get_owned(s, Campaign, campaign_id, uid)
    new = note is None
    note = note or Note(campaign_id=campaign_id)
    note.title = _text(data.get("title"), "Título", 160, True)
    note.content = _text(data.get("content"), "Conteúdo", 20000, True)
    note.category = _choice(data.get("category") or "outros", C.NOTE_CATEGORIES, "Categoria")
    note.important, note.archived = bool(data.get("important")), bool(data.get("archived"))
    character_id = data.get("character_id") or None
    if character_id:
        (character,) = load_in_campaign(s, Character, [character_id], campaign_id, "personagens")
        note.character_id, note.player_id = character.id, character.player_id
    else:
        player_id = data.get("player_id") or None
        if player_id:
            get_owned(s, Player, player_id, uid)
        note.character_id, note.player_id = None, player_id
    if new:
        s.add(note)
    _commit(s)
    return note


def toggle_note(s: Session, uid: int, note_id: int, flag: str) -> None:
    if flag not in ("important", "archived"):
        raise AppError("Ação inválida.")
    note = get_owned(s, Note, note_id, uid)
    setattr(note, flag, not getattr(note, flag))
    _commit(s)


def delete_note(s: Session, uid: int, note_id: int) -> None:
    s.delete(get_owned(s, Note, note_id, uid))
    _commit(s, "Não foi possível excluir a nota.")


# ---------------------------------------------------------------- NPCs

NPC_TEXT = dict(nickname=("Apelido", 80), description=("Descrição", 5000), appearance=("Aparência", 5000),
                personality=("Personalidade", 5000), goals=("Objetivos", 5000), motivation=("Motivação", 5000),
                secrets=("Segredos", 5000), master_notes=("Observações privadas", 10000))


def save_npc(s: Session, user: User, campaign_id: int, data: dict, npc: NPC | None = None) -> NPC:
    get_owned(s, Campaign, campaign_id, user.id)
    new = npc is None
    npc = npc or NPC(campaign_id=campaign_id)
    npc.name = _text(data.get("name"), "Nome", 120, True)
    npc.status = _choice(data.get("status") or "ativo", C.NPC_STATUS, "Status")
    for k, (label, n) in NPC_TEXT.items():
        setattr(npc, k, _text(data.get(k), label, n))
    _apply_image(s, user, npc, "image", data.get("image_path"), data.get("remove_image"))
    if new:
        s.add(npc)
    _commit(s)
    return npc


def delete_npc(s: Session, uid: int, npc_id: int) -> None:
    npc = get_owned(s, NPC, npc_id, uid)
    images.delete_image(s, uid, npc.image)
    s.delete(npc)
    _commit(s, "Não foi possível excluir o NPC.")


def add_relationship(s: Session, uid: int, npc_id: int, character_id: int, kind: str, description: str) -> None:
    npc = get_owned(s, NPC, npc_id, uid)
    (character,) = load_in_campaign(s, Character, [character_id], npc.campaign_id, "personagens")
    s.add(CharacterNPCRelationship(character_id=character.id, npc_id=npc.id,
                                   kind=_choice(kind, C.NPC_RELATIONS, "Tipo de relação"),
                                   description=_text(description, "Detalhes", 300)))
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise AppError("Essa relação já está registrada.") from None


def delete_relationship(s: Session, uid: int, rel_id: int) -> None:
    s.delete(get_owned(s, CharacterNPCRelationship, rel_id, uid))
    _commit(s)


# ---------------------------------------------------------------- missões

def save_quest(s: Session, uid: int, campaign_id: int, data: dict, quest: Quest | None = None) -> Quest:
    get_owned(s, Campaign, campaign_id, uid)
    new = quest is None
    old_status = None if new else quest.status
    quest = quest or Quest(campaign_id=campaign_id)
    quest.title = _text(data.get("title"), "Título", 160, True)
    quest.status = _choice(data.get("status") or "planejada", C.QUEST_STATUS, "Status")
    quest.deadline = data.get("deadline")
    quest.description = _text(data.get("description"), "Descrição", 10000)
    quest.rewards = _text(data.get("rewards"), "Recompensas", 5000)
    quest.master_notes = _text(data.get("master_notes"), "Observações privadas", 10000)
    npc_id = data.get("npc_id") or None
    if npc_id:
        (quest.npc,) = load_in_campaign(s, NPC, [npc_id], campaign_id, "NPCs")
    else:
        quest.npc = None
    quest.characters = load_in_campaign(s, Character, data.get("characters") or [], campaign_id, "personagens")
    if new or quest.status != old_status:
        quest.status_history.append(QuestStatusHistory(old_status=old_status, new_status=quest.status))
    if new:
        s.add(quest)
    _commit(s)
    return quest


def set_quest_status(s: Session, uid: int, quest_id: int, status: str) -> None:
    quest = get_owned(s, Quest, quest_id, uid)
    status = _choice(status, C.QUEST_STATUS, "Status")
    if status != quest.status:
        quest.status_history.append(QuestStatusHistory(old_status=quest.status, new_status=status))
        quest.status = status
        _commit(s)


def delete_quest(s: Session, uid: int, quest_id: int) -> None:
    s.delete(get_owned(s, Quest, quest_id, uid))
    _commit(s, "Não foi possível excluir a missão.")


def add_objective(s: Session, uid: int, quest_id: int, description: str) -> None:
    quest = get_owned(s, Quest, quest_id, uid)
    text = _text(description, "Objetivo", 300, True)
    quest.objectives.append(QuestObjective(description=text, position=max((o.position for o in quest.objectives), default=0) + 1))
    _commit(s)


def toggle_objective(s: Session, uid: int, objective_id: int) -> None:
    obj = get_owned(s, QuestObjective, objective_id, uid)
    obj.done = not obj.done
    _commit(s)


def delete_objective(s: Session, uid: int, objective_id: int) -> None:
    s.delete(get_owned(s, QuestObjective, objective_id, uid))
    _commit(s)


# ---------------------------------------------------------------- itens

def save_item(s: Session, uid: int, campaign_id: int, data: dict, item: Item | None = None) -> Item:
    get_owned(s, Campaign, campaign_id, uid)
    new = item is None
    item = item or Item(campaign_id=campaign_id)
    item.name = _text(data.get("name"), "Nome do item", 120, True)
    item.category = _choice(data.get("category") or "outro", C.ITEM_CATEGORIES, "Categoria")
    item.description = _text(data.get("description"), "Descrição", 5000)
    item.notes = _text(data.get("notes"), "Observações", 5000)
    if new:
        s.add(item)
        if data.get("character_id"):
            _add_holding(s, item, data["character_id"], data.get("quantity") or 1, data.get("origin"), data.get("quest_id"), None)
    _commit(s)
    return item


def _add_holding(s, item, character_id, quantity, origin, quest_id, notes) -> None:
    quantity = int(quantity)
    if not 1 <= quantity <= 1_000_000:
        raise AppError("A quantidade deve ser maior que zero.")
    (character,) = load_in_campaign(s, Character, [character_id], item.campaign_id, "personagens")
    quest = None
    if quest_id:
        (quest,) = load_in_campaign(s, Quest, [quest_id], item.campaign_id, "missões")
    item.holdings.append(CharacterItem(character=character, quantity=quantity, quest=quest,
                                       origin=_text(origin, "Origem", 200), notes=_text(notes, "Observações", 2000)))


def add_holding(s: Session, uid: int, item_id: int, character_id: int, quantity, origin=None, quest_id=None, notes=None):
    item = get_owned(s, Item, item_id, uid)
    _add_holding(s, item, character_id, quantity, origin, quest_id, notes)
    _commit(s)


def delete_holding(s: Session, uid: int, holding_id: int) -> None:
    s.delete(get_owned(s, CharacterItem, holding_id, uid))
    _commit(s)


def delete_item(s: Session, uid: int, item_id: int) -> None:
    s.delete(get_owned(s, Item, item_id, uid))
    _commit(s, "Não foi possível excluir o item.")


# ---------------------------------------------------------------- administração

def set_images_enabled(s: Session, admin: User, user_id: int, enabled: bool) -> User:
    if not admin.is_admin:
        raise AppError("Apenas administradores.")
    user = s.get(User, user_id)
    if user is None:
        raise AppError("Usuário não encontrado.")
    user.images_enabled = enabled
    if enabled:
        user.images_requested_at = None
    _commit(s)
    return user


__all__ = [n for n in dir() if not n.startswith("_")] + ["date"]
