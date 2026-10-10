from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QComboBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from mesa_desktop import db, paths
from mesa_desktop.models import Campaign, CampaignPlayer, Player
from mesa_desktop.services import messaging
from mesa_desktop.ui.kit import Page, attempt, button, page_header


def _sendable(p) -> bool:
    return bool(p.phone and p.messaging_consent)


class DraftCard(QFrame):
    def __init__(self, page: "MessagesPage", player_id: int, name: str, phone: str, text: str, direct: dict):
        super().__init__()
        self.setStyleSheet("QFrame { border: 1px solid #3b3748; border-radius: 10px; }")
        self.page, self.player_id, self.phone = page, player_id, phone
        lay = QVBoxLayout(self)
        title = QLabel(f"<b>{name}</b> <span style='color:#b7a9c7'>{phone}</span>")
        title.setStyleSheet("border: 0;")
        lay.addWidget(title)
        self.edit = QPlainTextEdit(text)
        self.edit.setMinimumHeight(130)
        lay.addWidget(self.edit)
        self.counter = QLabel("")
        self.counter.setObjectName("subtitle")
        self.counter.setStyleSheet("border: 0;")
        self.edit.textChanged.connect(self._count)
        self._count()
        lay.addWidget(self.counter)
        row = QHBoxLayout()
        row.addWidget(button("Abrir no WhatsApp", "primary", self._wa))
        row.addWidget(button("Abrir SMS", slot=self._sms))
        row.addWidget(button("Copiar texto", slot=self._copy))
        if direct.get("whatsapp"):
            row.addWidget(button("Enviar WhatsApp pelo servidor", slot=lambda: self._send("whatsapp")))
        if direct.get("sms"):
            row.addWidget(button("Enviar SMS pelo servidor", slot=lambda: self._send("sms")))
        row.addStretch()
        lay.addLayout(row)

    def text(self) -> str:
        return self.edit.toPlainText().strip()

    def _count(self):
        n = len(self.edit.toPlainText())
        over = n > messaging.MAX_BODY
        self.counter.setText(f"{n}/{messaging.MAX_BODY} caracteres" + ("  — acima do limite!" if over else ""))

    def _wa(self):
        QDesktopServices.openUrl(QUrl(messaging.wa_link(self.phone, self.text())))

    def _sms(self):
        QDesktopServices.openUrl(QUrl(messaging.sms_link(self.phone, self.text())))

    def _copy(self):
        QGuiApplication.clipboard().setText(self.text())
        self.page.info("Texto copiado.")

    def _send(self, channel: str):
        self.page.send_direct(self.player_id, channel, self.text())


class MessagesPage(Page):
    title = "Mensagens"
    needs_campaign = True

    def __init__(self, ctx, window):
        super().__init__(ctx, window)
        root = QVBoxLayout(self)
        head, _ = page_header("Mensagens aos jogadores",
                              "Só dados públicos: notas privadas e segredos nunca entram no texto. "
                              "Você revisa e envia pelo seu WhatsApp/SMS.")
        root.addWidget(head)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        ll.addWidget(QLabel("O que enviar"))
        self.kind = QComboBox()
        for key, label in messaging.KINDS:
            self.kind.addItem(label, key)
        ll.addWidget(self.kind)
        ll.addWidget(QLabel("Texto adicional (aceita {jogador} e {campanha})"))
        self.extra = QPlainTextEdit()
        self.extra.setMaximumHeight(90)
        ll.addWidget(self.extra)
        ll.addWidget(QLabel("Destinatários (precisam de telefone e consentimento)"))
        self.players = QListWidget()
        ll.addWidget(self.players, 1)
        ll.addWidget(button("Gerar prévia", "primary", self._preview))
        split.addWidget(left)
        self.out = QScrollArea()
        self.out.setWidgetResizable(True)
        self.out_body = QWidget()
        self.out_lay = QVBoxLayout(self.out_body)
        self.out_lay.addStretch()
        self.out.setWidget(self.out_body)
        split.addWidget(self.out)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
        self._cards: list[DraftCard] = []
        self._preselect: int | None = None

    def preselect(self, player_id: int):
        self._preselect = player_id

    def reload(self) -> None:
        with db.session() as s:
            rows = (s.query(Player).join(CampaignPlayer).filter(
                CampaignPlayer.campaign_id == self.ctx.campaign_id, CampaignPlayer.status == "ativo",
                Player.owner_id == self.ctx.user_id, Player.status != "arquivado").order_by(Player.display_name).all())
            data = [(p.id, p.display_name, p.phone, _sendable(p)) for p in rows]
        checked = {self.players.item(i).data(Qt.UserRole) for i in range(self.players.count())
                   if self.players.item(i).checkState() == Qt.Checked}
        if self._preselect:
            checked = {self._preselect}
            self._preselect = None
        self.players.clear()
        for pid, name, phone, ok in data:
            it = QListWidgetItem(name + (f"  ·  {phone}" if ok else "  ·  sem telefone/consentimento"))
            it.setData(Qt.UserRole, pid)
            if ok:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if pid in checked else Qt.Unchecked)
            else:
                it.setFlags(Qt.NoItemFlags)
            self.players.addItem(it)

    def _direct(self) -> dict:
        if not self.ctx.user.can_send_messages:
            return {"sms": False, "whatsapp": False}
        return messaging.server_channels(paths.load_settings().get("twilio", {}))

    def _preview(self):
        ids = [self.players.item(i).data(Qt.UserRole) for i in range(self.players.count())
               if self.players.item(i).flags() & Qt.ItemIsUserCheckable and self.players.item(i).checkState() == Qt.Checked]
        if not ids:
            self.info("Escolha ao menos um destinatário.")
            return
        kind, extra = self.kind.currentData(), self.extra.toPlainText()
        drafts, skipped = [], []

        def build(s, user):
            campaign = s.get(Campaign, self.ctx.campaign_id)
            for pid in ids:
                p = s.get(Player, pid)
                if p is None or p.owner_id != user.id or not _sendable(p):
                    continue
                text = messaging.build_text(s, kind, p, campaign, extra)
                (skipped if text is None else drafts).append((p.id, p.display_name, p.phone, text) if text else p.display_name)
        if not attempt(self, self.call, build)[0]:
            return
        for card in self._cards:
            card.setParent(None)
        self._cards = []
        direct = self._direct()
        for pid, name, phone, text in drafts:
            card = DraftCard(self, pid, name, phone, text, direct)
            self._cards.append(card)
            self.out_lay.insertWidget(self.out_lay.count() - 1, card)
        if skipped:
            self.info("Sem dados para: " + ", ".join(skipped))
        elif not drafts:
            self.info("Não há dados para enviar nesta categoria.")

    def send_direct(self, player_id: int, channel: str, body: str):
        cfg = paths.load_settings().get("twilio", {})
        limit = int(cfg.get("per_day", 30) or 30)

        def go(s, user):
            p = s.get(Player, player_id)
            if p is None or p.owner_id != user.id or not _sendable(p):
                raise messaging.SendError("Jogador sem telefone ou sem consentimento.")
            if not body or len(body) > messaging.MAX_BODY:
                raise messaging.SendError(f"A mensagem deve ter de 1 a {messaging.MAX_BODY} caracteres.")
            if messaging.sent_last_24h(s, user.id) >= limit:
                raise messaging.SendError("Limite diário de mensagens atingido. Use os links de WhatsApp/SMS.")
            try:
                sid = messaging.send_via_twilio(cfg, channel, p.phone, body)
            except messaging.SendError as exc:
                messaging.log_message(s, user.id, p.id, channel, False, error=str(exc), chars=len(body))
                raise
            messaging.log_message(s, user.id, p.id, channel, True, provider_id=sid, chars=len(body))
            return p.display_name

        from mesa_desktop.services.errors import AppError
        try:
            name = self.call(go)
        except messaging.SendError as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Envio não realizado", str(exc))
            return
        self.info(f"Enviado para {name}.")
