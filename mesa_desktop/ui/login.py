"""Tela de entrada: entrar, criar conta e recuperar senha (palavra-chave)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QFormLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from mesa_desktop import db, paths
from mesa_desktop.services import auth
from mesa_desktop.services.errors import AppError


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mesa do Mestre — entrar")
        self.setMinimumWidth(440)
        self.user_id: int | None = None
        lay = QVBoxLayout(self)
        brand = QLabel("⚔  Mesa do Mestre")
        brand.setObjectName("title")
        brand.setAlignment(Qt.AlignCenter)
        sub = QLabel("Campanhas, jogadores, XP, sessões e mais — no seu computador.")
        sub.setObjectName("subtitle")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        lay.addWidget(brand)
        lay.addWidget(sub)
        tabs = QTabWidget()
        lay.addWidget(tabs)
        self.error = QLabel("")
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        self.db_label = QLabel(f"Banco: {db.database_path()}")
        self.db_label.setObjectName("subtitle")
        self.db_label.setWordWrap(True)
        lay.addWidget(self.db_label)
        change = QPushButton("Trocar o arquivo do banco…")
        change.setProperty("kind", "flat")
        change.clicked.connect(self._change_db)
        lay.addWidget(change, 0, Qt.AlignLeft)

        # entrar
        tab = QWidget()
        form = QFormLayout(tab)
        self.l_email = QLineEdit(paths.load_settings().get("last_email", ""))
        self.l_pass = QLineEdit()
        self.l_pass.setEchoMode(QLineEdit.Password)
        form.addRow("E-mail", self.l_email)
        form.addRow("Senha", self.l_pass)
        go = QPushButton("Entrar")
        go.setProperty("kind", "primary")
        go.setDefault(True)
        go.clicked.connect(self._login)
        form.addRow(go)
        self.l_pass.returnPressed.connect(self._login)
        tabs.addTab(tab, "Entrar")

        # criar conta
        tab = QWidget()
        form = QFormLayout(tab)
        self.r_name, self.r_email = QLineEdit(), QLineEdit()
        self.r_pass, self.r_conf, self.r_phrase = QLineEdit(), QLineEdit(), QLineEdit()
        for w in (self.r_pass, self.r_conf):
            w.setEchoMode(QLineEdit.Password)
        form.addRow("Seu nome", self.r_name)
        form.addRow("E-mail", self.r_email)
        form.addRow("Senha", self.r_pass)
        form.addRow("Confirmar senha", self.r_conf)
        form.addRow("Palavra-chave de recuperação", self.r_phrase)
        hint = QLabel("Senha: mínimo de 8 caracteres, com letras e números. Não há recuperação por e-mail: "
                      "guarde a palavra-chave (mín. 6 caracteres). A primeira conta de um banco vazio vira administradora.")
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        form.addRow(hint)
        btn = QPushButton("Criar conta")
        btn.setProperty("kind", "primary")
        btn.clicked.connect(self._register)
        form.addRow(btn)
        tabs.addTab(tab, "Criar conta")

        # recuperar
        tab = QWidget()
        form = QFormLayout(tab)
        self.p_email, self.p_phrase = QLineEdit(), QLineEdit()
        self.p_new, self.p_conf = QLineEdit(), QLineEdit()
        for w in (self.p_new, self.p_conf):
            w.setEchoMode(QLineEdit.Password)
        form.addRow("E-mail", self.p_email)
        form.addRow("Palavra-chave", self.p_phrase)
        form.addRow("Nova senha", self.p_new)
        form.addRow("Confirmar nova senha", self.p_conf)
        btn = QPushButton("Redefinir senha")
        btn.clicked.connect(self._reset)
        form.addRow(btn)
        tabs.addTab(tab, "Recuperar senha")
        self.tabs = tabs

    def _change_db(self):
        path, _ = QFileDialog.getSaveFileName(self, "Escolher ou criar o arquivo do banco",
                                              str(db.database_path()), "Banco SQLite (*.sqlite3 *.db)",
                                              options=QFileDialog.DontConfirmOverwrite)
        if not path:
            return
        try:
            db.close_database()
            db.open_database(path)
        except db.SchemaError as exc:
            QMessageBox.critical(self, "Banco incompatível", str(exc))
            db.close_database()
            db.open_database(paths.database_path())
            return
        data = paths.load_settings()
        data["database"] = path
        paths.save_settings(data)
        self.db_label.setText(f"Banco: {db.database_path()}")
        self.error.setText("")

    def _fail(self, msg: str):
        self.error.setText(msg)

    def _login(self):
        try:
            with db.session() as s:
                user = auth.authenticate(s, self.l_email.text(), self.l_pass.text())
                uid = user.id
        except AppError as exc:
            self._fail(str(exc))
            return
        data = paths.load_settings()
        data["last_email"] = self.l_email.text().strip()
        paths.save_settings(data)
        self.user_id = uid
        self.accept()

    def _register(self):
        if self.r_pass.text() != self.r_conf.text():
            self._fail("As senhas não conferem.")
            return
        try:
            with db.session() as s:
                user = auth.register_user(s, self.r_name.text(), self.r_email.text(), self.r_pass.text(), self.r_phrase.text())
                self.user_id = user.id
        except AppError as exc:
            self._fail(str(exc))
            return
        self.accept()

    def _reset(self):
        if self.p_new.text() != self.p_conf.text():
            self._fail("As senhas não conferem.")
            return
        try:
            with db.session() as s:
                auth.reset_password_with_passphrase(s, self.p_email.text(), self.p_phrase.text(), self.p_new.text())
        except AppError as exc:
            self._fail(str(exc))
            return
        self.error.setText("")
        QMessageBox.information(self, "Senha redefinida", "Senha alterada. Entre com a nova senha.")
        self.l_email.setText(self.p_email.text())
        self.tabs.setCurrentIndex(0)
