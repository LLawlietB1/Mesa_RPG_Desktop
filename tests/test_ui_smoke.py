"""Teste de fumaça da interface: abre cada tela com dados de exemplo (Qt offscreen) e confere que nada quebra."""
import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mesa_desktop import db  # noqa: E402
from mesa_desktop.services import crud, xp  # noqa: E402


@pytest.fixture()
def qapp():
    from mesa_desktop.app import make_app
    return make_app([])


@pytest.fixture()
def window(qapp, database, png_file, monkeypatch, tmp_path):
    monkeypatch.setattr("mesa_desktop.paths.SETTINGS_DIR", tmp_path / "cfg")
    monkeypatch.setattr("mesa_desktop.paths.SETTINGS_FILE", tmp_path / "cfg" / "config.json")
    from mesa_desktop.services import auth
    with db.session() as s:
        admin = auth.register_user(s, "Dono", "dono@example.com", "senha-forte-1", "palavra dono")
        camp = crud.save_campaign(s, admin, {"name": "Reino de Teste", "status": "ativa", "system": "D&D 5e",
                                             "description": "Uma campanha de <teste> & mais.",
                                             "settings_text": "Marco: 3 sessões", "cover_path": png_file})
        ana = crud.save_player(s, admin.id, {"display_name": "Ana", "phone": "11 99999-8888", "messaging_consent": True})
        bia = crud.save_player(s, admin.id, {"display_name": "Bia"})
        herói = crud.save_character(s, admin, camp.id, {"name": "Herói", "player_id": ana.id, "race": "Elfo",
                                                        "char_class": "Mago", "level": 3, "portrait_path": png_file,
                                                        "extra_text": "Força: 10"})
        crud.save_character(s, admin, camp.id, {"name": "Ladina", "player_id": bia.id})
        xp.apply_delta(s, herói, 35, "Boss")
        sess = crud.save_session(s, admin.id, camp.id, {"number": 1, "title": "Início", "date": date.today(),
                                                        "participants": [herói.id], "summary": "Tudo começou."})
        crud.add_session_event(s, admin.id, sess.id, "O dragão caiu", herói.id)
        crud.save_note(s, admin.id, camp.id, {"title": "Segredo", "content": "Texto da nota", "important": True,
                                              "character_id": herói.id})
        npc = crud.save_npc(s, admin, camp.id, {"name": "Mago Velho", "secrets": "É o vilão", "image_path": png_file})
        crud.add_relationship(s, admin.id, npc.id, herói.id, "mentor", "Ensinou magia")
        q = crud.save_quest(s, admin.id, camp.id, {"title": "Resgate", "characters": [herói.id], "npc_id": npc.id})
        crud.add_objective(s, admin.id, q.id, "Achar a chave")
        crud.save_item(s, admin.id, camp.id, {"name": "Espada", "category": "equipamento", "character_id": herói.id, "quantity": 2})
        uid = admin.id
    from mesa_desktop.ui.kit import Ctx
    from mesa_desktop.ui.main_window import MainWindow
    win = MainWindow(Ctx(uid))
    win.resize(1280, 800)
    win.show()
    yield win
    win.close()


def test_every_page_loads_and_renders(window, qapp, tmp_path):
    out = tmp_path / "shots"
    out.mkdir()
    for key in window.keys:
        window.goto(key)
        page = window.pages[key]
        page.reload()
        if hasattr(page, "table") and hasattr(page.table, "selectRow") and page.table.rowCount():
            page.table.selectRow(0)
            qapp.processEvents()
        qapp.processEvents()
        window.grab().save(str(out / f"{key}.png"))
    assert len(list(out.glob("*.png"))) == len(window.keys)
    if os.environ.get("MESA_SHOTS"):
        import shutil
        shutil.copytree(out, os.environ["MESA_SHOTS"], dirs_exist_ok=True)


def test_campaign_switch_reloads(window, qapp):
    window.goto("characters")
    page = window.pages["characters"]
    assert page.table.rowCount() == 2
    window.goto("players")
    assert window.pages["players"].table.rowCount() == 2


def test_edit_dialogs_roundtrip_without_errors(window, qapp, monkeypatch):
    """Abre o formulário de edição de cada tela com o registro selecionado e salva sem alterar nada."""
    from PySide6.QtWidgets import QDialog, QMessageBox
    from mesa_desktop.ui import kit

    def auto_accept(self):
        self.accept()
        return self.result()

    def no_boxes(*a, **k):
        raise AssertionError("caixa de aviso inesperada: " + " ".join(str(x) for x in a[1:3]))

    monkeypatch.setattr(kit.FormDialog, "exec", auto_accept)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(no_boxes))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(no_boxes))
    saved = []
    for key in ("campaigns", "players", "characters", "sessions", "notes", "npcs", "quests", "items"):
        window.goto(key)
        page = window.pages[key]
        page.reload()
        assert page.table.rowCount() >= 1, key
        page.table.selectRow(0)
        item_id = page.table.current_id()
        page.on_edit(item_id)
        saved.append(key)
    assert len(saved) == 8


def test_new_item_dialog_creates_record(window, qapp, monkeypatch):
    from mesa_desktop.ui import kit
    page = window.pages["notes"]
    window.goto("notes")
    before = page.table.rowCount()

    def fill_and_accept(self):
        self._w["title"].setText("Nota criada pela interface")
        self._w["content"].setPlainText("Conteúdo")
        self.accept()
        return self.result()

    monkeypatch.setattr(kit.FormDialog, "exec", fill_and_accept)
    page.on_new()
    page.reload()
    assert page.table.rowCount() == before + 1


def test_login_dialog_register_login_and_errors(qapp, database, monkeypatch, tmp_path):
    from mesa_desktop.ui.login import LoginDialog
    monkeypatch.setattr("mesa_desktop.paths.SETTINGS_DIR", tmp_path / "cfg")
    monkeypatch.setattr("mesa_desktop.paths.SETTINGS_FILE", tmp_path / "cfg" / "config.json")
    dlg = LoginDialog()
    dlg.r_name.setText("Nova")
    dlg.r_email.setText("nova@example.com")
    dlg.r_pass.setText("senha-forte-1")
    dlg.r_conf.setText("diferente-1")
    dlg.r_phrase.setText("palavra nova")
    dlg._register()
    assert "não conferem" in dlg.error.text() and dlg.user_id is None
    dlg.r_conf.setText("senha-forte-1")
    dlg._register()
    assert dlg.user_id is not None

    again = LoginDialog()
    again.l_email.setText("nova@example.com")
    again.l_pass.setText("errada-123")
    again._login()
    assert "incorretos" in again.error.text() and again.user_id is None
    again.l_pass.setText("senha-forte-1")
    again._login()
    assert again.user_id == dlg.user_id
