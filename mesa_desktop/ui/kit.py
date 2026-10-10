"""Componentes de interface reutilizáveis: contexto da aplicação, formulários, páginas lista+detalhe, HTML."""
from __future__ import annotations

import html as _html
import traceback
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from PySide6.QtCore import QDate, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPixmap, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QInputDialog, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from mesa_desktop import db, paths
from mesa_desktop.models import Campaign, User
from mesa_desktop.services import images
from mesa_desktop.services.errors import AppError
from mesa_desktop.ui import theme


# ---------------------------------------------------------------- contexto

@dataclass
class UserInfo:
    id: int
    name: str
    email: str
    role: str
    can_upload_images: bool
    can_send_messages: bool
    images_requested: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"


class Ctx(QObject):
    """Estado compartilhado da sessão: usuário logado, campanha atual e sinais de atualização."""

    campaign_changed = Signal()
    data_changed = Signal()
    user_changed = Signal()

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.user: UserInfo = self._load_user()
        self.campaign_id: int | None = None
        self._pick_default_campaign()

    # -- usuário
    def _load_user(self) -> UserInfo:
        with db.session() as s:
            u = s.get(User, self.user_id)
            return UserInfo(u.id, u.name, u.email, u.role, u.can_upload_images, bool(u.can_send_messages),
                            bool(u.images_requested_at))

    def refresh_user(self) -> None:
        self.user = self._load_user()
        self.user_changed.emit()

    # -- campanha atual
    def campaigns(self) -> list[tuple[int, str, str]]:
        with db.session() as s:
            rows = (s.query(Campaign.id, Campaign.name, Campaign.status).filter_by(owner_id=self.user_id)
                    .order_by(Campaign.status == "encerrada", Campaign.name).all())
        return [(r.id, r.name, r.status) for r in rows]

    def _pick_default_campaign(self) -> None:
        camps = self.campaigns()
        saved = paths.load_settings().get("last_campaign", {}).get(str(self.user_id))
        ids = [c[0] for c in camps]
        if saved in ids:
            self.campaign_id = saved
        else:
            open_ones = [c for c in camps if c[2] != "encerrada"] or camps
            self.campaign_id = max((c[0] for c in open_ones), default=None)

    def set_campaign(self, campaign_id: int | None, notify=True) -> None:
        self.campaign_id = campaign_id
        data = paths.load_settings()
        data.setdefault("last_campaign", {})[str(self.user_id)] = campaign_id
        paths.save_settings(data)
        if notify:
            self.campaign_changed.emit()

    def campaign_name(self) -> str:
        for cid, name, _ in self.campaigns():
            if cid == self.campaign_id:
                return name
        return ""

    def changed(self) -> None:
        """Chame depois de qualquer alteração de dados para as telas se atualizarem."""
        ids = [c[0] for c in self.campaigns()]
        if self.campaign_id not in ids:
            self.set_campaign(max(ids, default=None), notify=False)
        self.data_changed.emit()


# ---------------------------------------------------------------- mensagens

def attempt(parent, fn: Callable, *args, **kwargs):
    """Executa `fn`; erros de regra viram aviso. Devolve (ok, resultado)."""
    try:
        return True, fn(*args, **kwargs)
    except AppError as exc:
        QMessageBox.warning(parent, "Atenção", str(exc))
    except Exception as exc:                                    # noqa: BLE001 - nada deve derrubar o programa
        QMessageBox.critical(parent, "Erro inesperado", f"{exc}\n\n{traceback.format_exc(limit=3)}")
    return False, None


def confirm(parent, text: str, title="Confirmar", danger=False) -> bool:
    box = QMessageBox(QMessageBox.Warning if danger else QMessageBox.Question, title, text,
                      QMessageBox.Yes | QMessageBox.No, parent)
    box.button(QMessageBox.Yes).setText("Sim")
    box.button(QMessageBox.No).setText("Não")
    box.setDefaultButton(QMessageBox.No)
    return box.exec() == QMessageBox.Yes


def button(text: str, kind: str = "", slot: Callable | None = None, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if slot:
        b.clicked.connect(lambda _=False: slot())
    if tip:
        b.setToolTip(tip)
    return b


# ---------------------------------------------------------------- HTML

def h(value) -> str:
    return _html.escape("" if value is None else str(value))


def para(text: str | None) -> str:
    return h(text).replace("\n", "<br>") if text else '<span class="muted">—</span>'


def section(title: str, body: str) -> str:
    return f"<h2>{h(title)}</h2>{body}"


def kv(pairs: list[tuple[str, str]]) -> str:
    rows = "".join(f'<tr><th>{h(k)}</th><td>{v}</td></tr>' for k, v in pairs)
    return f"<table>{rows}</table>"


def bar_html(percent: int, width: int = 220) -> str:
    """Barra de progresso em HTML (tabela de largura fixa: o percentual nunca quebra de linha)."""
    done = max(0, min(100, percent)) * width // 100
    left = width - done
    cells = f'<td width="{done}" bgcolor="{theme.ACCENT}" height="10"></td>' if done else ""
    rest = f'<td width="{left}" bgcolor="{theme.SURFACE2}" height="10"></td>' if left else ""
    return (f'<table cellspacing="0" cellpadding="0" width="{width + 56}"><tr>'
            f'<td width="48" align="right"><b>{percent}%</b></td><td width="8"></td>{cells}{rest}</tr></table>')


def link(action: str, label: str, arg=None, danger=False) -> str:
    target = f"{action}:{arg}" if arg is not None else action
    style = f' style="color:{theme.DANGER}"' if danger else ""
    return f'<a href="{h(target)}"{style}>{h(label)}</a>'


# ---------------------------------------------------------------- formulários

@dataclass
class F:
    """Especificação de um campo de formulário."""
    key: str
    label: str
    kind: str = "text"        # text | multiline | int | date | choice | multi | check | image | password
    options: list = field(default_factory=list)      # [(valor, rótulo)] para choice/multi
    required: bool = False
    hint: str = ""
    minimum: int = 0
    maximum: int = 999999
    blank: str | None = None  # rótulo da opção vazia em choice (valor None)
    image_bytes: bytes | None = None
    image_enabled: bool = True
    height: int = 90


class FormDialog(QDialog):
    """Formulário genérico. `submit(values)` roda ao salvar; um AppError mantém o diálogo aberto."""

    def __init__(self, parent, title: str, fields: list[F], values: dict | None = None,
                 submit: Callable[[dict], object] | None = None, intro: str = "", save_label: str = "Salvar",
                 width: int = 560):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(min(width, 520))
        self.resize(width, 200)
        self._submit, self._fields, self._w = submit, fields, {}
        self.result_value = None
        outer = QVBoxLayout(self)
        if intro:
            lab = QLabel(intro)
            lab.setWordWrap(True)
            lab.setObjectName("subtitle")
            outer.addWidget(lab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        form = QFormLayout(body)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        values = values or {}
        for f in fields:
            w = self._make(f, values.get(f.key))
            self._w[f.key] = w
            label = f.label + (" *" if f.required else "")
            if f.hint:
                box = QWidget()
                lay = QVBoxLayout(box)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.addWidget(w)
                hint = QLabel(f.hint)
                hint.setObjectName("subtitle")
                hint.setWordWrap(True)
                lay.addWidget(hint)
                form.addRow(label, box)
            else:
                form.addRow(label, w)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.error = QLabel("")
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        buttons = QDialogButtonBox()
        ok = buttons.addButton(save_label, QDialogButtonBox.AcceptRole)
        ok.setProperty("kind", "primary")
        buttons.addButton("Cancelar", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        total = min(720, 150 + sum(70 if f.kind in ("multiline", "multi", "image") else 42 for f in fields))
        self.resize(width, total)

    # -- construção dos campos
    def _make(self, f: F, value):
        if f.kind in ("text", "password"):
            w = QLineEdit(value or "")
            if f.kind == "password":
                w.setEchoMode(QLineEdit.Password)
            return w
        if f.kind == "multiline":
            w = QPlainTextEdit(value or "")
            w.setMinimumHeight(f.height)
            w.setTabChangesFocus(True)
            return w
        if f.kind == "int":
            w = QSpinBox()
            w.setRange(f.minimum - (0 if f.required else 1), f.maximum)
            if not f.required:
                w.setSpecialValueText(" ")
            w.setValue(value if value is not None else (f.minimum if f.required else f.minimum - 1))
            return w
        if f.kind == "date":
            box = QWidget()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            check = QCheckBox("definir")
            edit = QDateEdit(QDate.currentDate())
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("dd/MM/yyyy")
            if isinstance(value, date):
                edit.setDate(QDate(value.year, value.month, value.day))
            check.setChecked(value is not None or f.required)
            check.setVisible(not f.required)
            edit.setEnabled(check.isChecked())
            check.toggled.connect(edit.setEnabled)
            lay.addWidget(check)
            lay.addWidget(edit, 1)
            box.check, box.edit = check, edit
            return box
        if f.kind == "choice":
            w = QComboBox()
            if f.blank:
                w.addItem(f.blank, None)
            for val, lab in f.options:
                w.addItem(lab, val)
            idx = w.findData(value)
            w.setCurrentIndex(idx if idx >= 0 else 0)
            return w
        if f.kind == "multi":
            w = QListWidget()
            w.setMinimumHeight(110)
            chosen = set(value or [])
            for val, lab in f.options:
                it = QListWidgetItem(lab)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if val in chosen else Qt.Unchecked)
                it.setData(Qt.UserRole, val)
                w.addItem(it)
            return w
        if f.kind == "check":
            w = QCheckBox()
            w.setChecked(bool(value))
            return w
        if f.kind == "image":
            return _ImagePicker(f)
        raise ValueError(f.kind)

    # -- leitura
    def values(self) -> dict:
        out: dict = {}
        for f in self._fields:
            w = self._w[f.key]
            if f.kind in ("text", "password"):
                out[f.key] = w.text()
            elif f.kind == "multiline":
                out[f.key] = w.toPlainText()
            elif f.kind == "int":
                v = w.value()
                out[f.key] = None if (not f.required and v < f.minimum) else v
            elif f.kind == "date":
                d = w.edit.date()
                out[f.key] = date(d.year(), d.month(), d.day()) if w.check.isChecked() else None
            elif f.kind == "choice":
                out[f.key] = w.currentData()
            elif f.kind == "multi":
                out[f.key] = [w.item(i).data(Qt.UserRole) for i in range(w.count()) if w.item(i).checkState() == Qt.Checked]
            elif f.kind == "check":
                out[f.key] = w.isChecked()
            elif f.kind == "image":
                out[f"{f.key}_path"], out[f"remove_{f.key}"] = w.path, w.remove
        return out

    def accept(self):
        values = self.values()
        for f in self._fields:
            if f.required and f.kind in ("text", "multiline") and not (values[f.key] or "").strip():
                self.error.setText(f"{f.label}: campo obrigatório.")
                return
            if f.required and f.kind == "choice" and values[f.key] in (None, 0):
                self.error.setText(f"{f.label}: selecione uma opção.")
                return
        if self._submit is not None:
            try:
                self.result_value = self._submit(values)
            except AppError as exc:
                self.error.setText(str(exc))
                return
        else:
            self.result_value = values
        super().accept()


class _ImagePicker(QWidget):
    def __init__(self, f: F):
        super().__init__()
        self.path, self.remove = None, False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.preview = QLabel()
        self.preview.setFixedSize(72, 72)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(f"border: 1px solid {theme.BORDER}; border-radius: 8px;")
        self._set_pixmap(f.image_bytes)
        self.info = QLabel("Sem imagem" if not f.image_bytes else "Imagem atual")
        self.info.setObjectName("subtitle")
        self.choose = button("Escolher…", slot=self._pick)
        self.clear = button("Remover", slot=self._clear)
        col = QVBoxLayout()
        col.addWidget(self.info)
        row = QHBoxLayout()
        row.addWidget(self.choose)
        row.addWidget(self.clear)
        row.addStretch()
        col.addLayout(row)
        lay.addWidget(self.preview)
        lay.addLayout(col, 1)
        if not f.image_enabled:
            self.choose.setEnabled(False)
            self.clear.setEnabled(False)
            self.info.setText(images.NOT_ENABLED)
            self.info.setWordWrap(True)

    def _set_pixmap(self, data: bytes | None):
        pm = QPixmap()
        if data and pm.loadFromData(data):
            self.preview.setPixmap(pm.scaled(70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.preview.clear()

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Escolher imagem", "", "Imagens (*.png *.jpg *.jpeg *.gif *.webp)")
        if path:
            self.path, self.remove = path, False
            self.info.setText(path.replace("\\", "/").rsplit("/", 1)[-1])
            pm = QPixmap(path)
            self.preview.setPixmap(pm.scaled(70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _clear(self):
        self.path, self.remove = None, True
        self.preview.clear()
        self.info.setText("Imagem será removida ao salvar")


def ask_text(parent, title: str, label: str, multiline=False, value="") -> str | None:
    dlg = FormDialog(parent, title, [F("v", label, "multiline" if multiline else "text", required=True)], {"v": value},
                     width=460)
    return dlg.values()["v"].strip() if dlg.exec() == QDialog.Accepted and dlg.result_value else None


# ---------------------------------------------------------------- tabela

class DataTable(QTableWidget):
    """Tabela somente leitura, com id por linha e cores por status."""

    def __init__(self, columns: list[tuple[str, int]]):
        super().__init__(0, len(columns))
        self.setHorizontalHeaderLabels([c[0] for c in columns])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setHighlightSections(False)
        main = next((i for i, (_, w) in enumerate(columns) if not w), None)
        for i, (_, w) in enumerate(columns):
            self.setColumnWidth(i, w or 190)
        self.horizontalHeader().setStretchLastSection(main is None or main == len(columns) - 1)
        if main is not None and main != len(columns) - 1:
            self.horizontalHeader().setSectionResizeMode(main, QHeaderView.Stretch)

    def fill(self, rows: list[tuple[int, list[str], str | None]], keep: int | None = None) -> None:
        self.setRowCount(0)
        self.setRowCount(len(rows))
        target = None
        for r, (rid, cells, status) in enumerate(rows):
            for c, text in enumerate(cells):
                it = QTableWidgetItem(str(text))
                it.setData(Qt.UserRole, rid)
                if status and c == len(cells) - 1:
                    it.setForeground(QColor(theme.BADGE_COLORS.get(status, theme.TEXT2)))
                self.setItem(r, c, it)
            if rid == keep:
                target = r
        if target is not None:
            self.selectRow(target)

    def current_id(self) -> int | None:
        row = self.currentRow()
        if row < 0 or self.item(row, 0) is None:
            return None
        return self.item(row, 0).data(Qt.UserRole)


class Detail(QTextBrowser):
    """Painel HTML; links `acao:argumento` viram o sinal `action(acao, argumento)`."""

    action = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.document().setDefaultStyleSheet(theme.HTML_CSS)
        self.anchorClicked.connect(self._clicked)
        self._n = 0

    def _clicked(self, url: QUrl):
        raw = url.toString()
        if raw.startswith(("http://", "https://", "sms:")):
            QDesktopServices.openUrl(url)
            return
        name, _, arg = raw.partition(":")
        self.action.emit(name, arg)

    def show_html(self, body: str, pictures: dict[str, bytes] | None = None) -> None:
        for name, data in (pictures or {}).items():
            pm = QPixmap()
            if pm.loadFromData(data):
                self.document().addResource(QTextDocument.ImageResource, QUrl(name), pm.scaledToWidth(
                    min(pm.width(), 220), Qt.SmoothTransformation))
        bar = self.verticalScrollBar().value()
        self.setHtml(body)
        self.verticalScrollBar().setValue(bar)

    def placeholder(self, text: str) -> None:
        self.setHtml(f'<p class="muted">{h(text)}</p>')


# ---------------------------------------------------------------- páginas

class Page(QWidget):
    """Base de toda tela: acesso ao contexto e título."""

    title = ""
    needs_campaign = False

    def __init__(self, ctx: Ctx, window):
        super().__init__()
        self.ctx, self.win = ctx, window

    def reload(self) -> None:
        pass

    def changed(self) -> None:
        self.ctx.changed()

    def call(self, fn):
        """Abre uma sessão do banco e chama fn(sessão, usuário). Erros de regra (AppError) sobem a quem chamou."""
        with db.session() as s:
            user = s.get(User, self.ctx.user_id)
            return fn(s, user)

    def choose(self, title: str, label: str, options: list, current=None):
        """Escolha simples em uma lista [(valor, rótulo)]. Devolve o valor ou None."""
        labels = [lab for _, lab in options]
        start = next((i for i, (v, _) in enumerate(options) if v == current), 0)
        text, ok = QInputDialog.getItem(self, title, label, labels, start, False)
        return options[labels.index(text)][0] if ok else None

    def info(self, text: str) -> None:
        self.win.statusBar().showMessage(text, 6000)


def page_header(title: str, subtitle: str = "") -> tuple[QWidget, QHBoxLayout]:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    col = QVBoxLayout()
    t = QLabel(title)
    t.setObjectName("title")
    col.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("subtitle")
        col.addWidget(s)
    lay.addLayout(col, 1)
    return box, lay


class ListDetailPage(Page):
    """Lista (com busca e filtros) à esquerda e painel de detalhe à direita."""

    columns: list[tuple[str, int]] = []
    filters: list[tuple[str, str, list]] = []     # (chave, rótulo, [(valor, rótulo)]) — 1ª opção = «todos»
    search_hint = "Buscar…"
    new_label = "Novo"
    empty_text = "Nada cadastrado ainda."

    def __init__(self, ctx, window):
        super().__init__(ctx, window)
        self._filters: dict[str, QComboBox] = {}
        root = QVBoxLayout(self)
        head, head_lay = page_header(self.title, self.subtitle())
        self.btn_new = button("＋ " + self.new_label, "primary", self.on_new)
        head_lay.addWidget(self.btn_new)
        root.addWidget(head)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.search_hint)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _=None: self.reload())
        bar.addWidget(self.search, 1)
        for key, label, options in self.filters:
            cb = QComboBox()
            cb.setToolTip(label)
            for val, lab in options:
                cb.addItem(lab, val)
            cb.currentIndexChanged.connect(lambda _=None: self.reload())
            self._filters[key] = cb
            bar.addWidget(cb)
        self.filter_bar = QWidget()
        self.filter_bar.setLayout(bar)
        bar.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.filter_bar)

        self.table = DataTable(self.columns)
        self.detail = Detail()
        self.detail.action.connect(self.on_link)
        self.table.itemSelectionChanged.connect(self._selected)
        self.table.itemDoubleClicked.connect(lambda _it: self.on_edit(self.table.current_id()) if self.table.current_id() else None)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.actions_bar = QHBoxLayout()
        self.btn_edit = button("Editar", slot=lambda: self._need(self.on_edit))
        self.btn_delete = button("Excluir", "danger", lambda: self._need(self.on_delete))
        self.actions_bar.addWidget(self.btn_edit)
        self.extra_buttons: list[tuple[QPushButton, Callable]] = []
        for label, fn in self.extra_actions():
            b = button(label, slot=lambda fn=fn: self._need(fn))
            self.extra_buttons.append((b, fn))
            self.actions_bar.addWidget(b)
        self.actions_bar.addStretch()
        self.actions_bar.addWidget(self.btn_delete)
        rl.addLayout(self.actions_bar)
        rl.addWidget(self.detail, 1)

        self.split = QSplitter(Qt.Horizontal)
        self.split.addWidget(self.table)
        self.split.addWidget(right)
        self.table.setMinimumWidth(360)
        self.split.setStretchFactor(0, 5)
        self.split.setStretchFactor(1, 5)
        self.split.setChildrenCollapsible(False)
        root.addWidget(self.split, 1)
        self._set_actions_enabled(False)
        self.detail.placeholder("Selecione um item na lista." if True else "")

    # -- a sobrescrever
    def subtitle(self) -> str:
        return ""

    def rows(self, s, q: str, flt: dict) -> list[tuple[int, list[str], str | None]]:
        return []

    def detail_html(self, s, item_id: int) -> tuple[str, dict]:
        return "", {}

    def on_new(self): ...
    def on_edit(self, item_id: int): ...
    def on_delete(self, item_id: int): ...
    def extra_actions(self) -> list[tuple[str, Callable]]:
        return []

    def on_link(self, action: str, arg: str): ...

    # -- mecânica
    def filter_values(self) -> dict:
        return {k: cb.currentData() for k, cb in self._filters.items()}

    def _need(self, fn):
        item_id = self.table.current_id()
        if item_id is not None:
            fn(item_id)

    def _set_actions_enabled(self, on: bool):
        self.btn_edit.setEnabled(on)
        self.btn_delete.setEnabled(on)
        for b, _ in self.extra_buttons:
            b.setEnabled(on)

    def _selected(self):
        self._set_actions_enabled(self.table.current_id() is not None)
        self.refresh_detail()

    def refresh_detail(self):
        item_id = self.table.current_id()
        if item_id is None:
            self.detail.placeholder("Selecione um item na lista." if self.table.rowCount() else self.empty_text)
            return
        with db.session() as s:
            body, pics = self.detail_html(s, item_id)
        self.detail.show_html(body, pics)

    def reload(self) -> None:
        keep = self.table.current_id()
        with db.session() as s:
            rows = self.rows(s, self.search.text().strip(), self.filter_values())
        self.table.blockSignals(True)
        self.table.fill(rows, keep)
        self.table.blockSignals(False)
        self._set_actions_enabled(self.table.current_id() is not None)
        self.refresh_detail()

    def select(self, item_id: int) -> None:
        self.reload()
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == item_id:
                self.table.selectRow(r)
                break

    def resizeEvent(self, ev):                     # telas estreitas: lista em cima, detalhe embaixo
        self.split.setOrientation(Qt.Vertical if self.width() < 820 else Qt.Horizontal)
        super().resizeEvent(ev)

    def do_form(self, title: str, fields: list[F], values: dict | None, submit, intro="", width=600):
        dlg = FormDialog(self, title, fields, values, submit, intro=intro, width=width)
        return dlg.result_value if dlg.exec() == QDialog.Accepted else None


class NoCampaign(QWidget):
    """Aviso mostrado em telas que dependem de uma campanha quando ainda não há nenhuma."""

    def __init__(self, on_create: Callable):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addStretch()
        t = QLabel("Crie a primeira campanha para começar")
        t.setObjectName("title")
        t.setAlignment(Qt.AlignCenter)
        s = QLabel("Cada campanha é independente: jogadores, personagens, notas, sessões, NPCs, missões e itens ficam separados.")
        s.setObjectName("subtitle")
        s.setAlignment(Qt.AlignCenter)
        s.setWordWrap(True)
        b = button("＋ Nova campanha", "primary", on_create)
        lay.addWidget(t)
        lay.addWidget(s)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        lay.addStretch()
