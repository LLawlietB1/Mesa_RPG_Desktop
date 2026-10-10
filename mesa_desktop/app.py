"""Inicialização do programa: abre o banco compartilhado, mostra o login e a janela principal."""
from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from mesa_desktop import db, paths
from mesa_desktop.ui import theme
from mesa_desktop.ui.kit import Ctx
from mesa_desktop.ui.login import LoginDialog
from mesa_desktop.ui.main_window import MainWindow


def make_app(argv=None) -> QApplication:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("Mesa do Mestre")
    app.setStyleSheet(theme.QSS)
    icon = paths.RES_DIR / "assets" / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    return app


def run(argv=None) -> int:
    app = make_app(argv)
    path = paths.database_path()
    try:
        db.open_database(path)
    except db.SchemaError as exc:
        QMessageBox.critical(None, "Banco incompatível", str(exc))
        return 2
    except Exception as exc:                                  # noqa: BLE001
        QMessageBox.critical(None, "Não foi possível abrir o banco", f"{path}\n\n{exc}")
        return 2
    while True:
        login = LoginDialog()
        if login.exec() != QDialog.Accepted or login.user_id is None:
            return 0
        window = MainWindow(Ctx(login.user_id))
        window.show()
        app.exec()
        if not window.logged_out:
            return 0
