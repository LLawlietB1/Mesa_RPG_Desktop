"""Backup, Minha conta, Administração e Configurações."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QSpinBox, QVBoxLayout, QWidget)

from mesa_desktop import __version__, db, paths
from mesa_desktop.models import User
from mesa_desktop.services import auth, backup, images
from mesa_desktop.ui.kit import (DataTable, F, FormDialog, Page, attempt, button, confirm, page_header)
from mesa_desktop.utils import fmt_datetime


def _label(text: str, subtle=True) -> QLabel:
    w = QLabel(text)
    w.setWordWrap(True)
    if subtle:
        w.setObjectName("subtitle")
    return w


class BackupPage(Page):
    title = "Backup"

    def __init__(self, ctx, window):
        super().__init__(ctx, window)
        root = QVBoxLayout(self)
        head, _ = page_header("Backup", "Exporta e restaura SOMENTE os dados da sua conta (JSON + imagens em um .zip).")
        root.addWidget(head)
        box = QGroupBox("Exportar")
        bl = QVBoxLayout(box)
        bl.addWidget(_label("Gera um arquivo .zip com campanhas, jogadores, personagens, XP, notas, sessões, NPCs, "
                            "missões, inventário e imagens. O mesmo arquivo pode ser restaurado na versão web."))
        bl.addWidget(button("Exportar backup…", "primary", self._export))
        root.addWidget(box)
        box2 = QGroupBox("Restaurar")
        b2 = QVBoxLayout(box2)
        b2.addWidget(_label("A restauração SUBSTITUI todos os seus dados atuais pelos do arquivo, em uma única "
                            "transação: se algo falhar, nada é alterado. Os dados de outras contas nunca são tocados."))
        b2.addWidget(button("Restaurar de um backup…", "danger", self._restore))
        root.addWidget(box2)
        root.addStretch()

    def _export(self):
        ok, (name, blob) = attempt(self, self.call, lambda s, u: backup.create_backup(s, u))
        if not ok:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salvar backup", name, "Backup (*.zip)")
        if path:
            with open(path, "wb") as fh:
                fh.write(blob)
            self.info(f"Backup salvo em {path}")

    def _restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Escolher backup", "", "Backup (*.zip)")
        if not path:
            return
        if not confirm(self, "Isto vai SUBSTITUIR todos os seus dados atuais pelos do arquivo. Continuar?", danger=True):
            return
        ok, result = attempt(self, self.call, lambda s, u: backup.restore_backup(s, u, path))
        if ok:
            QMessageBox.information(self, "Backup restaurado",
                                    f"{result['rows']} registros e {result['images']} imagens restaurados.")
            self.ctx.set_campaign(None, notify=False)
            self.ctx._pick_default_campaign()
            self.changed()


class AccountPage(Page):
    title = "Minha conta"

    def __init__(self, ctx, window):
        super().__init__(ctx, window)
        root = QVBoxLayout(self)
        head, _ = page_header("Minha conta", "")
        root.addWidget(head)
        self.info_label = QLabel()
        self.info_label.setTextFormat(Qt.RichText)
        self.info_label.setWordWrap(True)
        root.addWidget(self.info_label)
        for text, kind, fn, tip in (
            ("Alterar senha…", "", self._password, ""),
            ("Alterar palavra-chave de recuperação…", "", self._recovery, "Sem e-mail: é ela que redefine sua senha."),
            ("Pedir liberação de imagens", "", self._request, "O administrador aprova em «Administração»."),
            ("Encerrar logins da versão web", "", self._end_web, "Obriga a entrar de novo no navegador."),
            ("Excluir minha conta…", "danger", self._delete, "Apaga a conta e TODOS os dados."),
        ):
            root.addWidget(button(text, kind, fn, tip))
        root.addStretch()

    def reload(self):
        u = self.ctx.user
        with db.session() as s:
            n = auth.web_session_count(s, s.get(User, u.id))
            used = images.used_bytes(s, u.id)
        imgs = ("liberado" if u.can_upload_images else ("pedido enviado, aguardando aprovação" if u.images_requested
                                                          else "não liberado"))
        self.info_label.setText(
            f"<p><b>{u.name}</b> — {u.email}<br>Papel: {'Administrador' if u.is_admin else 'Mestre'}<br>"
            f"Envio de imagens: {imgs} · uso {used / 1024:.0f} KB de {images.QUOTA_BYTES // 1024} KB<br>"
            f"Logins ativos na versão web: {n}</p>")

    def _password(self):
        res = FormDialog(self, "Alterar senha", [
            F("current", "Senha atual", "password", required=True),
            F("password", "Nova senha", "password", required=True, hint="Mínimo de 8 caracteres, com letras e números."),
            F("confirm", "Confirmar nova senha", "password", required=True)],
            submit=self._do_password, width=460)
        if res.exec():
            self.info("Senha alterada.")

    def _do_password(self, v):
        from mesa_desktop.services.errors import AppError
        if v["password"] != v["confirm"]:
            raise AppError("As senhas não conferem.")
        self.call(lambda s, u: auth.change_password(s, u, v["current"], v["password"]))

    def _recovery(self):
        dlg = FormDialog(self, "Palavra-chave de recuperação", [
            F("current", "Senha atual", "password", required=True),
            F("passphrase", "Nova palavra-chave", required=True, hint="Mínimo de 6 caracteres. Guarde-a: não há recuperação por e-mail.")],
            submit=lambda v: self.call(lambda s, u: auth.change_recovery(s, u, v["current"], v["passphrase"])), width=460)
        if dlg.exec():
            self.info("Palavra-chave atualizada.")

    def _request(self):
        ok, msg = attempt(self, self.call, lambda s, u: auth.request_images(s, u))
        if ok:
            QMessageBox.information(self, "Imagens", msg)
            self.ctx.refresh_user()
            self.reload()

    def _end_web(self):
        ok, n = attempt(self, self.call, lambda s, u: auth.end_web_sessions(s, u))
        if ok:
            self.info(f"{n} login(s) da versão web encerrado(s).")
            self.reload()

    def _delete(self):
        dlg = FormDialog(self, "Excluir conta", [
            F("current", "Senha atual", "password", required=True),
            F("confirm_text", "Digite EXCLUIR para confirmar", required=True)],
            submit=lambda v: self.call(lambda s, u: auth.delete_account(s, u, v["current"], v["confirm_text"])),
            intro="Isto apaga a sua conta e TODOS os seus dados, nas duas versões (web e desktop).",
            save_label="Excluir definitivamente", width=480)
        if dlg.exec():
            QMessageBox.information(self, "Conta excluída", "Sua conta foi excluída. O programa será fechado.")
            self.win.close()


class AdminPage(Page):
    title = "Administração"

    def __init__(self, ctx, window):
        super().__init__(ctx, window)
        root = QVBoxLayout(self)
        head, _ = page_header("Administração", "Liberar ou revogar o envio de imagens (controla o tamanho do banco).")
        root.addWidget(head)
        self.table = DataTable([("Nome", 160), ("E-mail", 0), ("Papel", 90), ("Imagens", 160), ("Uso", 90)])
        root.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(button("Liberar imagens", "primary", lambda: self._set(True)))
        row.addWidget(button("Revogar", "danger", lambda: self._set(False)))
        row.addStretch()
        root.addLayout(row)

    def reload(self):
        with db.session() as s:
            users = s.query(User).order_by(User.images_requested_at.is_(None), User.images_requested_at.desc(), User.name).all()
            rows = []
            for u in users:
                if u.can_upload_images:
                    st = "liberado" if not u.is_admin else "liberado (admin)"
                elif u.images_requested_at:
                    st = "PEDIDO PENDENTE — " + fmt_datetime(u.images_requested_at)
                else:
                    st = "não liberado"
                rows.append((u.id, [u.name, u.email, u.role, st, f"{images.used_bytes(s, u.id) / 1024:.0f} KB"], None))
        self.table.fill(rows)

    def _set(self, enabled: bool):
        uid = self.table.current_id()
        if uid is None:
            self.info("Selecione uma conta.")
            return
        from mesa_desktop.services import crud
        ok, user = attempt(self, self.call, lambda s, admin: crud.set_images_enabled(s, admin, uid, enabled))
        if ok:
            self.info(f"Envio de imagens {'liberado' if enabled else 'revogado'} para {user.name}.")
            if uid == self.ctx.user_id:
                self.ctx.refresh_user()
            self.reload()


class SettingsPage(Page):
    title = "Configurações"

    def __init__(self, ctx, window):
        super().__init__(ctx, window)
        root = QVBoxLayout(self)
        head, _ = page_header("Configurações", f"Mesa do Mestre Desktop {__version__}")
        root.addWidget(head)

        box = QGroupBox("Banco de dados (compartilhado com a versão web)")
        bl = QVBoxLayout(box)
        self.path_label = _label("", subtle=False)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bl.addWidget(self.path_label)
        bl.addWidget(_label("A versão web e este programa leem e gravam o MESMO arquivo: o que você faz em um aparece "
                            "no outro. Evite usar os dois exatamente ao mesmo tempo na mesma tela."))
        row = QHBoxLayout()
        row.addWidget(button("Trocar arquivo do banco…", slot=self._change_db))
        row.addWidget(button("Abrir a pasta", slot=self._open_folder))
        row.addStretch()
        bl.addLayout(row)
        root.addWidget(box)

        box2 = QGroupBox("Envio direto de SMS/WhatsApp (Twilio) — opcional")
        b2 = QVBoxLayout(box2)
        b2.addWidget(_label("Gera custo no seu provedor. Sem isto, os botões de WhatsApp/SMS por link continuam funcionando. "
                            "O envio direto também exige que sua conta esteja liberada para mensagens."))
        self.tw = {}
        form = QFormLayout()
        for key, label, secret in (("account_sid", "Account SID", False), ("auth_token", "Auth token", True),
                                   ("sms_from", "Número SMS (remetente)", False),
                                   ("whatsapp_from", "Número WhatsApp (remetente)", False)):
            w = QLineEdit()
            if secret:
                w.setEchoMode(QLineEdit.Password)
            self.tw[key] = w
            form.addRow(label, w)
        self.per_day = QSpinBox()
        self.per_day.setRange(1, 1000)
        form.addRow("Limite de mensagens por dia", self.per_day)
        self.cc = QLineEdit()
        form.addRow("Código do país padrão", self.cc)
        b2.addLayout(form)
        b2.addWidget(button("Salvar", "primary", self._save))
        root.addWidget(box2)
        root.addStretch()

    def reload(self):
        self.path_label.setText(f"<b>{db.database_path()}</b>")
        cfg = paths.load_settings()
        tw = cfg.get("twilio", {})
        for k, w in self.tw.items():
            w.setText(tw.get(k, ""))
        self.per_day.setValue(int(tw.get("per_day", 30) or 30))
        self.cc.setText(cfg.get("country_code", "55"))

    def _save(self):
        data = paths.load_settings()
        data["twilio"] = {k: w.text().strip() for k, w in self.tw.items()} | {"per_day": self.per_day.value()}
        data["country_code"] = self.cc.text().strip() or "55"
        paths.save_settings(data)
        self.info("Configurações salvas.")

    def _change_db(self):
        path, _ = QFileDialog.getSaveFileName(self, "Escolher ou criar o arquivo do banco", str(db.database_path()),
                                              "Banco SQLite (*.sqlite3 *.db)", options=QFileDialog.DontConfirmOverwrite)
        if not path:
            return
        data = paths.load_settings()
        data["database"] = path
        paths.save_settings(data)
        QMessageBox.information(self, "Banco alterado", "Feche e abra o programa novamente para usar o novo arquivo.")

    def _open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(db.database_path().parent)))
