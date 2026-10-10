import io
from datetime import date

import pytest
from sqlalchemy import text

from mesa_desktop import db
from mesa_desktop.models import Campaign, Character, ExperienceHistory, FileAsset, Player, User
from mesa_desktop.services import auth, backup, crud, images, messaging, xp
from mesa_desktop.services.errors import AppError
from tests.conftest import PASSWORD


# ---------------------------------------------------------------- banco / esquema

def test_new_database_is_stamped_with_current_revision(s):
    assert s.execute(text("select version_num from alembic_version")).scalar() == db.SCHEMA_REVISION


def test_foreign_keys_are_enforced(s, admin):
    s.add(Character(name="X", campaign_id=999, player_id=999))
    with pytest.raises(Exception):
        s.commit()


def test_wrong_revision_is_rejected(tmp_path):
    p = tmp_path / "velho.sqlite3"
    db.open_database(p)
    db.close_database()
    import sqlite3
    con = sqlite3.connect(p)
    con.execute("update alembic_version set version_num='antiga'")
    con.commit()
    con.close()
    with pytest.raises(db.SchemaError):
        db.open_database(p)


# ---------------------------------------------------------------- autenticação

def test_first_account_is_admin_second_is_not(admin, master):
    assert admin.role == "ADMIN" and master.role == "MESTRE"
    assert admin.can_upload_images and not master.can_upload_images


def test_login_lock_and_generic_message(s, master):
    for _ in range(5):
        with pytest.raises(AppError, match="incorretos"):
            auth.authenticate(s, "mestre@example.com", "errada-123")
    with pytest.raises(AppError, match="Muitas tentativas"):
        auth.authenticate(s, "mestre@example.com", PASSWORD)
    with pytest.raises(AppError, match="incorretos"):
        auth.authenticate(s, "ninguem@example.com", "x")


def test_login_ok_and_recovery(s, master):
    assert auth.authenticate(s, " MESTRE@example.com ", PASSWORD).id == master.id
    auth.reset_password_with_passphrase(s, "mestre@example.com", "Palavra Mestre", "nova-senha-9")
    assert auth.authenticate(s, "mestre@example.com", "nova-senha-9").id == master.id


def test_password_rules(s):
    with pytest.raises(AppError, match="letras e números"):
        auth.register_user(s, "A", "a@example.com", "somenteletras", "palavra")
    with pytest.raises(AppError, match="E-mail"):
        auth.register_user(s, "A", "invalido", PASSWORD, "palavra")


# ---------------------------------------------------------------- XP

@pytest.fixture()
def world(s, admin):
    c = crud.save_campaign(s, admin, {"name": "Campanha", "status": "ativa"})
    p = crud.save_player(s, admin.id, {"display_name": "Ana", "phone": "11 99999-8888", "messaging_consent": True})
    ch = crud.save_character(s, admin, c.id, {"name": "Herói", "player_id": p.id})
    return c, p, ch


def test_xp_flow(s, world):
    _, _, ch = world
    assert xp.apply_delta(s, ch, 10).new == 10
    assert xp.apply_delta(s, ch, 200 - 100).new == 100          # limitado a 100
    with pytest.raises(AppError):
        xp.apply_delta(s, ch, 0)
    r = xp.set_percent(s, ch, 100)
    assert not r.changed
    assert xp.start_new_cycle(s, ch).new == 0 and ch.xp_cycle == 2
    with pytest.raises(AppError, match="100%"):
        xp.start_new_cycle(s, ch)
    assert s.query(ExperienceHistory).filter_by(character_id=ch.id).count() == 3


def test_xp_bulk_is_atomic_and_same_campaign(s, admin, world):
    c, p, ch = world
    other = crud.save_campaign(s, admin, {"name": "Outra"})
    ch2 = crud.save_character(s, admin, other.id, {"name": "Fora", "player_id": p.id})
    with pytest.raises(AppError):
        xp.apply_bulk(s, c.id, [ch.id, ch2.id], 5)
    assert ch.xp_percent == 0
    results = xp.apply_bulk(s, c.id, [ch.id], 5, "bônus")
    assert results[0].new == 5


# ---------------------------------------------------------------- cadastros

def test_player_rules(s, admin, world):
    _, p, ch = world
    assert p.phone == "+5511999998888" and p.messaging_consent
    with pytest.raises(AppError, match="possui personagens"):
        crud.delete_player(s, admin.id, p)
    with pytest.raises(AppError, match="obrigatório"):
        crud.save_player(s, admin.id, {"display_name": " "})
    solo = crud.save_player(s, admin.id, {"display_name": "Solo", "messaging_consent": True})
    assert solo.messaging_consent is False                       # sem telefone não há consentimento
    crud.delete_player(s, admin.id, solo)


def test_isolation_between_accounts(s, admin, master, world):
    c, p, ch = world
    with pytest.raises(AppError):
        crud.get_owned(s, Campaign, c.id, master.id)
    with pytest.raises(AppError):
        crud.save_note(s, master.id, c.id, {"title": "x", "content": "y"})
    with pytest.raises(AppError):
        crud.delete_character(s, master.id, ch)


def test_session_number_unique_and_events(s, admin, world):
    c, p, ch = world
    sess = crud.save_session(s, admin.id, c.id, {"number": 1, "title": "Início", "date": date(2026, 1, 1),
                                                 "participants": [ch.id]})
    with pytest.raises(AppError, match="Já existe"):
        crud.save_session(s, admin.id, c.id, {"number": 1, "title": "Dup", "date": date(2026, 1, 2)})
    crud.add_session_event(s, admin.id, sess.id, "Dragão apareceu", ch.id)
    assert len(sess.events) == 1
    crud.delete_session(s, admin.id, sess)


def test_quest_history_and_objectives(s, admin, world):
    c, _, ch = world
    q = crud.save_quest(s, admin.id, c.id, {"title": "Resgate", "characters": [ch.id]})
    crud.set_quest_status(s, admin.id, q.id, "em_andamento")
    assert [h.new_status for h in q.status_history] == ["planejada", "em_andamento"] or len(q.status_history) == 2
    crud.add_objective(s, admin.id, q.id, "Achar a chave")
    crud.toggle_objective(s, admin.id, q.objectives[0].id)
    assert q.objectives[0].done


def test_items_and_holdings(s, admin, world):
    c, _, ch = world
    it = crud.save_item(s, admin.id, c.id, {"name": "Espada", "category": "equipamento", "character_id": ch.id, "quantity": 2})
    assert it.total_quantity == 2
    with pytest.raises(AppError):
        crud.add_holding(s, admin.id, it.id, ch.id, 0)


def test_npc_relationship_duplicate(s, admin, world):
    c, _, ch = world
    npc = crud.save_npc(s, admin, c.id, {"name": "Mago"})
    crud.add_relationship(s, admin.id, npc.id, ch.id, "amizade", "")
    with pytest.raises(AppError, match="já está registrada"):
        crud.add_relationship(s, admin.id, npc.id, ch.id, "amizade", "")


def test_delete_campaign_requires_exact_name_and_cascades(s, admin, world):
    c, p, ch = world
    with pytest.raises(AppError, match="nome exato"):
        crud.delete_campaign(s, admin.id, c, "errado")
    crud.delete_campaign(s, admin.id, c, "Campanha")
    assert s.query(Character).count() == 0 and s.query(Player).count() == 1


# ---------------------------------------------------------------- imagens

def test_image_requires_release_and_quota(s, admin, master, world, png_file):
    c, _, _ = world
    with pytest.raises(AppError, match="não foi liberado"):
        crud.save_campaign(s, master, {"name": "M", "cover_path": png_file})
    camp = crud.save_campaign(s, admin, {"name": "Com capa", "cover_path": png_file})
    asset = s.get(FileAsset, camp.cover_image)
    assert asset.content_type == "image/webp" and images.image_bytes(s, admin.id, camp.cover_image)
    crud.save_campaign(s, admin, {"name": "Com capa", "remove_cover": True}, camp)
    assert camp.cover_image is None and s.query(FileAsset).count() == 0


def test_fake_image_is_rejected(s, admin, tmp_path):
    f = tmp_path / "falso.png"
    f.write_bytes(b"isso nao e uma imagem")
    with pytest.raises(AppError, match="imagem válida"):
        crud.save_campaign(s, admin, {"name": "X", "cover_path": str(f)})


# ---------------------------------------------------------------- backup

def test_backup_roundtrip_remaps_ids_and_keeps_other_users(s, admin, master, world, png_file):
    c, p, ch = world
    crud.save_campaign(s, admin, {"name": "Campanha", "cover_path": png_file}, c)
    crud.add_session_event(s, admin.id, crud.save_session(s, admin.id, c.id, {"number": 1, "title": "S", "date": date(2026, 1, 1)}).id, "Algo", ch.id)
    other = crud.save_campaign(s, master, {"name": "Do Mestre"})
    name, blob = backup.create_backup(s, admin)
    assert name.endswith(".zip") and b"mestre@example.com" not in blob and b"Do Mestre" not in blob
    crud.delete_campaign(s, admin.id, c, "Campanha")
    result = backup.restore_backup(s, admin, io.BytesIO(blob))
    assert result["images"] == 1
    assert [x.name for x in s.query(Campaign).filter_by(owner_id=admin.id)] == ["Campanha"]
    assert s.get(Campaign, other.id).name == "Do Mestre"
    restored = s.query(Character).join(Campaign).filter(Campaign.owner_id == admin.id).one()
    assert restored.name == "Herói" and restored.player.display_name == "Ana"


def test_backup_rejects_garbage(s, admin):
    with pytest.raises(AppError):
        backup.restore_backup(s, admin, io.BytesIO(b"nao e zip"))


# ---------------------------------------------------------------- mensagens

def test_message_text_has_no_private_data(s, admin, world):
    c, p, ch = world
    crud.save_character(s, admin, c.id, {"name": "Herói", "player_id": p.id, "master_notes": "SEGREDO-MESTRE"}, ch)
    s.refresh(p)
    text = messaging.build_text(s, "personagem", p, c, "Boa sorte, {jogador}!")
    assert "Herói" in text and "XP: 0%" in text and "Boa sorte, Ana!" in text and "SEGREDO-MESTRE" not in text
    assert messaging.build_text(s, "proxima_sessao", p, c) is None


def test_phone_and_links():
    assert messaging.normalize_phone("(11) 99999-8888") == "+5511999998888"
    with pytest.raises(messaging.PhoneError):
        messaging.normalize_phone("123")
    assert messaging.wa_link("+5511999998888", "oi mundo").startswith("https://wa.me/5511999998888?text=oi%20mundo")
