"""Tema escuro (mesma paleta do app web) e CSS dos painéis de detalhe em HTML."""

BG, BG_DEEP, SURFACE, SURFACE2 = "#17151d", "#110f16", "#25232c", "#2d2a36"
PRIMARY, ACCENT, ACCENT_STRONG = "#342344", "#9c7ad0", "#b394e6"
TEXT, TEXT2, BORDER = "#f1eaf8", "#b7a9c7", "#3b3748"
SUCCESS, WARNING, DANGER, INFO = "#5fbf8f", "#e0b25a", "#e0707e", "#7aa7e0"

BADGE_COLORS = {
    "ativo": SUCCESS, "ativa": SUCCESS, "realizada": SUCCESS, "concluida": SUCCESS,
    "planejada": INFO, "agendada": INFO, "disponivel": INFO, "em_andamento": ACCENT_STRONG,
    "pausada": WARNING, "inativo": WARNING, "afastado": WARNING, "desaparecido": WARNING, "desconhecido": TEXT2,
    "encerrada": TEXT2, "arquivado": TEXT2, "aposentado": TEXT2, "abandonada": TEXT2,
    "cancelada": DANGER, "morto": DANGER, "fracassada": DANGER,
}

QSS = f"""
* {{ font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 10pt; }}
QWidget {{ background: {BG}; color: {TEXT}; }}
QToolTip {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
QMainWindow, QDialog {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 18pt; font-weight: 600; }}
QLabel#subtitle {{ color: {TEXT2}; }}
QLabel#error {{ color: {DANGER}; }}
QLabel#brand {{ font-size: 13pt; font-weight: 600; color: {ACCENT_STRONG}; padding: 6px 4px; }}

QFrame#sidebar {{ background: {BG_DEEP}; border-right: 1px solid {BORDER}; }}
QFrame#sidebar QWidget {{ background: transparent; }}
QListWidget#nav {{ border: 0; outline: 0; }}
QListWidget#nav::item {{ padding: 9px 12px; border-radius: 8px; margin: 1px 4px; color: {TEXT2}; }}
QListWidget#nav::item:hover {{ background: {SURFACE}; color: {TEXT}; }}
QListWidget#nav::item:selected {{ background: {PRIMARY}; color: {TEXT}; border-left: 3px solid {ACCENT}; }}

QPushButton {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 14px; min-height: 22px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {PRIMARY}; }}
QPushButton:disabled {{ color: #6f647c; background: {SURFACE}; }}
QPushButton[kind="primary"] {{ background: {ACCENT}; color: #14101a; border-color: {ACCENT}; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: {ACCENT_STRONG}; }}
QPushButton[kind="danger"] {{ background: #4a2229; border-color: #7d3340; color: #ffd9de; }}
QPushButton[kind="danger"]:hover {{ border-color: {DANGER}; }}
QPushButton[kind="flat"] {{ background: transparent; border: 0; color: {ACCENT_STRONG}; padding: 4px 6px; }}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDateEdit, QComboBox, QListWidget, QTableWidget, QTextBrowser {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 8px;
    selection-background-color: {PRIMARY}; selection-color: {TEXT}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDateEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: {PRIMARY}; }}
QTextBrowser {{ padding: 12px; }}
QListWidget::item {{ padding: 4px 6px; }}
QListWidget::item:selected {{ background: {PRIMARY}; }}

QTableWidget {{ gridline-color: transparent; alternate-background-color: {SURFACE2}; padding: 0; }}
QTableWidget::item {{ padding: 6px 8px; border: 0; }}
QTableWidget::item:selected {{ background: {PRIMARY}; color: {TEXT}; }}
QHeaderView::section {{ background: {BG_DEEP}; color: {TEXT2}; border: 0; border-bottom: 1px solid {BORDER};
    padding: 7px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {BG_DEEP}; border: 0; }}

QProgressBar {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 8px; text-align: center; min-height: 18px; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {PRIMARY}, stop:1 {ACCENT}); border-radius: 7px; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{ background: {BG_DEEP}; color: {TEXT2}; padding: 8px 16px; border: 1px solid {BORDER};
    border-bottom: 0; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {SURFACE}; color: {TEXT}; }}

QGroupBox {{ border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px; padding: 14px 10px 10px 10px; background: {SURFACE}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {ACCENT_STRONG}; font-weight: 600; background: transparent; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {BORDER}; border-radius: 4px; background: {SURFACE}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 28px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 28px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QStatusBar {{ background: {BG_DEEP}; color: {TEXT2}; border-top: 1px solid {BORDER}; }}
QMessageBox {{ background: {BG}; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {PRIMARY}; }}
"""

# CSS dos painéis HTML (QTextBrowser aceita só um subconjunto do CSS)
HTML_CSS = f"""
body {{ color: {TEXT}; background: {SURFACE}; }}
h1 {{ font-size: 18pt; color: {TEXT}; margin-bottom: 2px; }}
h2 {{ font-size: 11pt; color: {ACCENT_STRONG}; margin-top: 16px; margin-bottom: 4px; }}
a {{ color: {ACCENT_STRONG}; text-decoration: none; }}
.muted {{ color: {TEXT2}; }}
.small {{ font-size: 9pt; }}
td, th {{ padding: 3px 8px 3px 0; vertical-align: top; }}
th {{ color: {TEXT2}; text-align: left; font-weight: normal; }}
.danger {{ color: {DANGER}; }}
"""


def badge_html(key: str, label: str | None = None) -> str:
    color = BADGE_COLORS.get(key, TEXT2)
    text = (label or key).replace("_", " ")
    return f'<span style="color:{color}; font-weight:600;">● {text}</span>'
