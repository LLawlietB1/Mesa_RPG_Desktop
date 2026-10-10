"""Modelos SQLAlchemy mapeados nas MESMAS tabelas do app web (Mesa do Mestre).

Este arquivo precisa permanecer compativel com as migrations do projeto web (MesaDoMestre). Qualquer mudanca de
esquema deve nascer la (flask db migrate) e ser replicada aqui."""

from datetime import datetime, timezone


from sqlalchemy import (JSON, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, LargeBinary,
                        String, Table, Text, UniqueConstraint, false)

from sqlalchemy.orm import DeclarativeBase, deferred, relationship


from mesa_desktop.constants import (CAMPAIGN_STATUS, CHARACTER_STATUS, ITEM_CATEGORIES, NOTE_CATEGORIES, NPC_RELATIONS,
                                    NPC_STATUS, PLAYER_STATUS, QUEST_STATUS, SESSION_STATUS, XP_ORIGINS, in_clause)



class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Datas/horas sao guardadas em UTC sem tzinfo (igual ao app web)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)



# ---- user
class User(TimestampMixin, Base):
    """Conta de um mestre. Todos os dados de negócio pertencem a um usuário (isolamento total)."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('MESTRE','ADMIN')", name="ck_user_role"),)

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(200), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    recovery_hash = Column(String(255))          # palavra-chave de recuperação (hash)
    role = Column(String(10), nullable=False, default="MESTRE")
    failed_logins = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime)
    # Envio de mensagens pelo servidor consome crédito do provedor: liberado manualmente (flask grant-messaging).
    can_send_messages = Column(Boolean, nullable=False, default=False)
    # Upload de imagens: liberado manualmente (controla o armazenamento do banco), como no Professor Helper.
    images_enabled = Column(Boolean, nullable=False, default=False, server_default=false())
    images_requested_at = Column(DateTime)

    @property
    def is_admin(self):
        return self.role == "ADMIN"

    @property
    def can_upload_images(self):
        return self.is_admin or self.images_enabled

    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)


class UserSession(Base):
    """Sessão de login. Só o hash SHA-256 do token é guardado: ler o banco não permite forjar o cookie."""

    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    ip = Column(String(64))
    user_agent = Column(String(200))
    created_at = Column(DateTime, nullable=False, default=utcnow)

    user = relationship("User", back_populates="sessions")


class FileAsset(Base):
    """Imagem enviada (retrato, capa, NPC). O conteúdo fica no próprio banco (`data`) e é servido só ao dono
    em /media/<id>."""

    __tablename__ = "file_assets"

    id = Column(String(32), primary_key=True)    # uuid4 hex gerado no servidor
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    content_type = Column(String(40), nullable=False)
    size = Column(Integer, nullable=False)
    data = deferred(Column(LargeBinary, nullable=False))
    created_at = Column(DateTime, nullable=False, default=utcnow)


class MessageLog(Base):
    """Registro de mensagens enviadas pelo servidor (sem o texto: só metadados)."""

    __tablename__ = "message_logs"
    __table_args__ = (CheckConstraint("channel IN ('sms','whatsapp')", name="ck_message_channel"),)

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="SET NULL"), index=True)
    channel = Column(String(10), nullable=False)
    ok = Column(Boolean, nullable=False)
    provider_id = Column(String(64))
    error = Column(String(300))
    chars = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)


# ---- campaign
class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"
    __table_args__ = (CheckConstraint(in_clause("status", CAMPAIGN_STATUS), name="ck_campaign_status"),)

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False, index=True)
    description = Column(Text)
    system = Column(String(80))
    setting = Column(String(120))
    start_date = Column(Date)
    status = Column(String(20), nullable=False, default="planejada", index=True)
    notes = Column(Text)
    settings = Column(JSON, nullable=False, default=dict)  # configurações específicas (chave/valor)
    cover_image = Column(String(100))

    memberships = relationship("CampaignPlayer", back_populates="campaign", cascade="all, delete-orphan", passive_deletes=True)
    characters = relationship("Character", back_populates="campaign", cascade="all, delete-orphan", passive_deletes=True, order_by="Character.name")
    notes_list = relationship("Note", back_populates="campaign", cascade="all, delete-orphan", passive_deletes=True)
    sessions = relationship("GameSession", back_populates="campaign", cascade="all, delete-orphan", passive_deletes=True, order_by="GameSession.number")
    npcs = relationship("NPC", back_populates="campaign", cascade="all, delete-orphan", passive_deletes=True)
    quests = relationship("Quest", back_populates="campaign", cascade="all, delete-orphan", passive_deletes=True)
    items = relationship("Item", back_populates="campaign", cascade="all, delete-orphan", passive_deletes=True)

    @property
    def is_closed(self):
        return self.status == "encerrada"

    def __repr__(self):
        return f"<Campaign {self.id} {self.name!r}>"


class Player(TimestampMixin, Base):
    __tablename__ = "players"
    __table_args__ = (CheckConstraint(in_clause("status", PLAYER_STATUS), name="ck_player_status"),)

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name = Column(String(120), nullable=False, index=True)
    real_name = Column(String(120))
    nickname = Column(String(80))
    email = Column(String(200))
    phone = Column(String(20))                     # E.164 (ex.: +5511999998888), opcional
    messaging_consent = Column(Boolean, nullable=False, default=False)
    notes = Column(Text)
    status = Column(String(20), nullable=False, default="ativo", index=True)

    memberships = relationship("CampaignPlayer", back_populates="player", cascade="all, delete-orphan", passive_deletes=True)
    characters = relationship("Character", back_populates="player", order_by="Character.name")

    def __repr__(self):
        return f"<Player {self.id} {self.display_name!r}>"


class CampaignPlayer(Base):
    """Participação de um jogador em uma campanha (um jogador pode estar em várias)."""

    __tablename__ = "campaign_players"
    __table_args__ = (
        UniqueConstraint("campaign_id", "player_id", name="uq_campaign_player"),
        CheckConstraint("status IN ('ativo','saiu')", name="ck_campaign_player_status"),
    )

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(10), nullable=False, default="ativo")
    joined_at = Column(DateTime, nullable=False, default=utcnow)
    left_at = Column(DateTime)

    campaign = relationship("Campaign", back_populates="memberships")
    player = relationship("Player", back_populates="memberships")


# ---- character
class Character(TimestampMixin, Base):
    __tablename__ = "characters"
    __table_args__ = (
        CheckConstraint(in_clause("status", CHARACTER_STATUS), name="ck_character_status"),
        CheckConstraint("xp_percent BETWEEN 0 AND 100", name="ck_character_xp_percent"),
        Index("ix_characters_campaign_name", "campaign_id", "name"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="RESTRICT"), nullable=False, index=True)
    system = Column(String(80))
    race = Column(String(80))
    char_class = Column(String(80))
    level = Column(Integer)
    portrait = Column(String(100))
    backstory = Column(Text)
    personality = Column(Text)
    goals = Column(Text)
    background = Column(Text)
    status = Column(String(20), nullable=False, default="ativo", index=True)
    master_notes = Column(Text)
    extra = Column(JSON, nullable=False, default=dict)  # atributos específicos do sistema (chave/valor)

    # Barra de XP manual (0-100). `xp_points` reserva espaço para XP numérica futura.
    xp_percent = Column(Integer, nullable=False, default=0)
    xp_cycle = Column(Integer, nullable=False, default=1)
    xp_points = Column(Integer)

    campaign = relationship("Campaign", back_populates="characters")
    player = relationship("Player", back_populates="characters")
    xp_history = relationship(
        "ExperienceHistory", back_populates="character", cascade="all, delete-orphan",
        passive_deletes=True, order_by="ExperienceHistory.id.desc()",
    )

    def __repr__(self):
        return f"<Character {self.id} {self.name!r}>"


class ExperienceHistory(Base):
    __tablename__ = "experience_history"
    __table_args__ = (
        CheckConstraint("previous_percent BETWEEN 0 AND 100 AND new_percent BETWEEN 0 AND 100", name="ck_xp_history_range"),
        CheckConstraint(in_clause("origin", XP_ORIGINS), name="ck_xp_history_origin"),
    )

    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    previous_percent = Column(Integer, nullable=False)
    new_percent = Column(Integer, nullable=False)
    delta = Column(Integer, nullable=False)              # variação efetivamente aplicada
    requested_delta = Column(Integer)                    # variação pedida (pode diferir se houve limite)
    cycle = Column(Integer, nullable=False, default=1)
    reason = Column(String(300))
    origin = Column(String(20), nullable=False, default="individual")
    batch_id = Column(String(36), index=True)            # agrupa alterações coletivas
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)

    character = relationship("Character", back_populates="xp_history")


# ---- session
# Associações simples (sem atributos extras). SessionParticipant da especificação = session_participants.
session_participants = Table(
    "session_participants", Base.metadata,
    Column("session_id", Integer, ForeignKey("game_sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
)
session_npcs = Table(
    "session_npcs", Base.metadata,
    Column("session_id", Integer, ForeignKey("game_sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("npc_id", Integer, ForeignKey("npcs.id", ondelete="CASCADE"), primary_key=True),
)
session_quests = Table(
    "session_quests", Base.metadata,
    Column("session_id", Integer, ForeignKey("game_sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("quest_id", Integer, ForeignKey("quests.id", ondelete="CASCADE"), primary_key=True),
)


class GameSession(TimestampMixin, Base):
    __tablename__ = "game_sessions"
    __table_args__ = (
        UniqueConstraint("campaign_id", "number", name="uq_session_campaign_number"),
        CheckConstraint(in_clause("status", SESSION_STATUS), name="ck_session_status"),
        CheckConstraint("number > 0", name="ck_session_number"),
    )

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    title = Column(String(160), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="agendada", index=True)
    summary = Column(Text)
    pending = Column(Text)
    master_notes = Column(Text)

    campaign = relationship("Campaign", back_populates="sessions")
    participants = relationship("Character", secondary=session_participants, order_by="Character.name")
    npcs = relationship("NPC", secondary=session_npcs, order_by="NPC.name")
    quests = relationship("Quest", secondary=session_quests, order_by="Quest.title")
    events = relationship(
        "SessionEvent", back_populates="session", cascade="all, delete-orphan",
        passive_deletes=True, order_by="SessionEvent.id",
    )


class SessionEvent(Base):
    """Acontecimento importante de uma sessão, opcionalmente ligado a um personagem."""

    __tablename__ = "session_events"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="SET NULL"), index=True)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)

    session = relationship("GameSession", back_populates="events")
    character = relationship("Character")


# ---- note
class Note(TimestampMixin, Base):
    __tablename__ = "notes"
    __table_args__ = (CheckConstraint(in_clause("category", NOTE_CATEGORIES), name="ck_note_category"),)

    id = Column(Integer, primary_key=True)
    title = Column(String(160), nullable=False, index=True)
    content = Column(Text, nullable=False)
    category = Column(String(20), nullable=False, default="outros", index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="SET NULL"), index=True)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="SET NULL"), index=True)
    important = Column(Boolean, nullable=False, default=False)
    archived = Column(Boolean, nullable=False, default=False, index=True)

    campaign = relationship("Campaign", back_populates="notes_list")
    player = relationship("Player")
    character = relationship("Character")


# ---- npc
class NPC(TimestampMixin, Base):
    __tablename__ = "npcs"
    __table_args__ = (CheckConstraint(in_clause("status", NPC_STATUS), name="ck_npc_status"),)

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False, index=True)
    nickname = Column(String(80))
    description = Column(Text)
    appearance = Column(Text)
    personality = Column(Text)
    goals = Column(Text)
    motivation = Column(Text)
    secrets = Column(Text)
    status = Column(String(20), nullable=False, default="ativo", index=True)
    image = Column(String(100))
    master_notes = Column(Text)

    campaign = relationship("Campaign", back_populates="npcs")
    relationships = relationship(
        "CharacterNPCRelationship", back_populates="npc", cascade="all, delete-orphan", passive_deletes=True,
    )


class CharacterNPCRelationship(Base):
    __tablename__ = "character_npc_relationships"
    __table_args__ = (
        UniqueConstraint("character_id", "npc_id", "kind", name="uq_character_npc_kind"),
        CheckConstraint(in_clause("kind", NPC_RELATIONS), name="ck_relationship_kind"),
    )

    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True)
    npc_id = Column(Integer, ForeignKey("npcs.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False, default="neutro")
    description = Column(String(300))

    character = relationship("Character")
    npc = relationship("NPC", back_populates="relationships")


# ---- item
class Item(Base):
    """Item/tesouro/moeda registrado na campanha. Quem o possui fica em CharacterItem."""

    __tablename__ = "items"
    __table_args__ = (CheckConstraint(in_clause("category", ITEM_CATEGORIES), name="ck_item_category"),)

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False, index=True)
    description = Column(Text)
    category = Column(String(20), nullable=False, default="outro", index=True)
    notes = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    campaign = relationship("Campaign", back_populates="items")
    holdings = relationship(
        "CharacterItem", back_populates="item", cascade="all, delete-orphan", passive_deletes=True,
    )

    @property
    def total_quantity(self):
        return sum(h.quantity for h in self.holdings)


class CharacterItem(Base):
    __tablename__ = "character_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_character_item_quantity"),)

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    origin = Column(String(200))
    quest_id = Column(Integer, ForeignKey("quests.id", ondelete="SET NULL"))
    notes = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    item = relationship("Item", back_populates="holdings")
    character = relationship("Character")
    quest = relationship("Quest")


# ---- quest
# QuestCharacter da especificação = quest_characters
quest_characters = Table(
    "quest_characters", Base.metadata,
    Column("quest_id", Integer, ForeignKey("quests.id", ondelete="CASCADE"), primary_key=True),
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
)


class Quest(TimestampMixin, Base):
    __tablename__ = "quests"
    __table_args__ = (CheckConstraint(in_clause("status", QUEST_STATUS), name="ck_quest_status"),)

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(160), nullable=False, index=True)
    description = Column(Text)
    npc_id = Column(Integer, ForeignKey("npcs.id", ondelete="SET NULL"), index=True)
    rewards = Column(Text)  # registro administrativo; não altera fichas nem inventários
    deadline = Column(Date)
    status = Column(String(20), nullable=False, default="planejada", index=True)
    master_notes = Column(Text)

    campaign = relationship("Campaign", back_populates="quests")
    npc = relationship("NPC")
    characters = relationship("Character", secondary=quest_characters, order_by="Character.name")
    objectives = relationship(
        "QuestObjective", back_populates="quest", cascade="all, delete-orphan",
        passive_deletes=True, order_by="QuestObjective.position, QuestObjective.id",
    )
    status_history = relationship(
        "QuestStatusHistory", back_populates="quest", cascade="all, delete-orphan",
        passive_deletes=True, order_by="QuestStatusHistory.id.desc()",
    )


class QuestObjective(Base):
    __tablename__ = "quest_objectives"

    id = Column(Integer, primary_key=True)
    quest_id = Column(Integer, ForeignKey("quests.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(String(300), nullable=False)
    done = Column(Boolean, nullable=False, default=False)
    position = Column(Integer, nullable=False, default=0)

    quest = relationship("Quest", back_populates="objectives")


class QuestStatusHistory(Base):
    __tablename__ = "quest_status_history"

    id = Column(Integer, primary_key=True)
    quest_id = Column(Integer, ForeignKey("quests.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status = Column(String(20))
    new_status = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    quest = relationship("Quest", back_populates="status_history")
