"""Janela principal: navegação lateral, seletor de campanha e páginas."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from mesa_desktop import __version__
from mesa_desktop.ui.kit import Ctx, NoCampaign
from mesa_desktop.ui.pages.account import AccountPage, AdminPage, BackupPage, SettingsPage
from mesa_desktop.ui.pages.campaigns import CampaignsPage
from mesa_desktop.ui.pages.characters import CharactersPage
from mesa_desktop.ui.pages.dashboard import DashboardPage
from mesa_desktop.ui.pages.items import ItemsPage
from mesa_desktop.ui.pages.messages import MessagesPage
from mesa_desktop.ui.pages.notes import NotesPage
from mesa_desktop.ui.pages.npcs import NPCsPage
from mesa_desktop.ui.pages.players import PlayersPage
from mesa_desktop.ui.pages.quests import QuestsPage
from mesa_desktop.ui.pages.sessions import SessionsPage
from mesa_desktop.ui.pages.xp import XPPage

NAV = [
    ("dashboard", "⌂  Painel", DashboardPage),
    ("campaigns", "⚑  Campanhas", CampaignsPage),
    ("players", "☺  Jogadores", PlayersPage),
    ("characters", "♞  Personagens", CharactersPage),
    ("xp", "★  Experiência", XPPage),
    ("sessions", "☷  Sessões", SessionsPage),
    ("notes", "✎  Notas", NotesPage),
    ("npcs", "☻  NPCs", NPCsPage),
    ("quests", "⚔  Missões", QuestsPage),
    ("items", "⚗  Inventário", ItemsPage),
    ("messages", "✉  Mensagens", MessagesPage),
    ("backup", "⇩  Backup", BackupPage),
    ("admin", "⚙  Administração", AdminPage),
    ("account", "⚇  Minha conta", AccountPage),
    ("settings", "☰  Configurações", SettingsPage),
]


class MainWindow(QMainWindow):
    def __init__(self, ctx: Ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"Mesa do Mestre — {ctx.user.name}")
        self.resize(1280, 800)
        self.setMinimumSize(760, 520)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(230)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(8, 10, 8, 10)
        brand = QLabel("⚔  Mesa do Mestre")
        brand.setObjectName("brand")
        sl.addWidget(brand)
        self.campaign_box = QComboBox()
        self.campaign_box.setToolTip("Campanha atual")
        self.campaign_box.activated.connect(self._campaign_chosen)
        sl.addWidget(self.campaign_box)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        sl.addWidget(self.nav, 1)
        who = QLabel(f"{ctx.user.name}\n{ctx.user.email}")
        who.setObjectName("subtitle")
        who.setWordWrap(True)
        sl.addWidget(who)
        out = QPushButton("Sair")
        out.clicked.connect(self._logout)
        sl.addWidget(out)
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("subtitle")
        sl.addWidget(ver)
        root.addWidget(side)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.pages: dict[str, QWidget] = {}
        self.keys: list[str] = []
        self.nocampaign = NoCampaign(lambda: self.goto("campaigns", new=True))
        self.stack.addWidget(self.nocampaign)
        for key, label, cls in NAV:
            if key == "admin" and not ctx.user.is_admin:
                continue
            page = cls(ctx, self)
            self.pages[key] = page
            self.keys.append(key)
            self.stack.addWidget(page)
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            item.setSizeHint(QSize(0, 34))
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self._nav_changed)
        self.statusBar().showMessage(f"Banco: {self._db_path()}")

        ctx.campaign_changed.connect(self._campaign_changed)
        ctx.data_changed.connect(self._data_changed)
        ctx.user_changed.connect(self._fill_campaigns)
        self._fill_campaigns()
        self.nav.setCurrentRow(0)
        self.logged_out = False

    @staticmethod
    def _db_path():
        from mesa_desktop import db
        return db.database_path()

    # -- navegação
    def current_key(self) -> str:
        item = self.nav.currentItem()
        return item.data(Qt.UserRole) if item else "dashboard"

    def goto(self, key: str, new=False, select: int | None = None, preselect: int | None = None) -> None:
        if key not in self.pages:
            return
        row = self.keys.index(key)
        self.nav.setCurrentRow(row)
        page = self.pages[key]
        if preselect is not None and hasattr(page, "preselect"):
            page.preselect(preselect)
            page.reload()
        if select is not None and hasattr(page, "select"):
            page.select(select)
        if new and hasattr(page, "on_new"):
            QTimer.singleShot(0, page.on_new)

    def _nav_changed(self, row: int):
        if row < 0:
            return
        key = self.keys[row]
        page = self.pages[key]
        if page.needs_campaign and self.ctx.campaign_id is None:
            self.stack.setCurrentWidget(self.nocampaign)
            return
        self.stack.setCurrentWidget(page)
        page.reload()

    def _fill_campaigns(self):
        self.campaign_box.blockSignals(True)
        self.campaign_box.clear()
        camps = self.ctx.campaigns()
        if not camps:
            self.campaign_box.addItem("Nenhuma campanha", None)
        for cid, name, status in camps:
            self.campaign_box.addItem(name + (" (encerrada)" if status == "encerrada" else ""), cid)
        idx = self.campaign_box.findData(self.ctx.campaign_id)
        self.campaign_box.setCurrentIndex(max(idx, 0))
        self.campaign_box.blockSignals(False)

    def _campaign_chosen(self, _index: int):
        cid = self.campaign_box.currentData()
        if cid is not None and cid != self.ctx.campaign_id:
            self.ctx.set_campaign(cid)

    def _campaign_changed(self):
        self._fill_campaigns()
        self._nav_changed(self.nav.currentRow())

    def _data_changed(self):
        self._fill_campaigns()
        self._nav_changed(self.nav.currentRow())

    def _logout(self):
        self.logged_out = True
        self.close()
