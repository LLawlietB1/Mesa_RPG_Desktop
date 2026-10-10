from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QProgressBar, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from sqlalchemy.orm import selectinload

from mesa_desktop import constants as C
from mesa_desktop import db
from mesa_desktop.models import Character, ExperienceHistory
from mesa_desktop.services import crud, xp
from mesa_desktop.ui.kit import DataTable, F, FormDialog, Page, attempt, button, page_header
from mesa_desktop.utils import fmt_datetime

ORIGIN = dict(C.XP_ORIGINS)


class XPPage(Page):
    title = "Experiência"
    needs_campaign = True

    def __init__(self, ctx, window):
        super().__init__(ctx, window)
        root = QVBoxLayout(self)
        head, hl = page_header("Experiência", "Barra de XP manual (0–100%). O nível nunca sobe sozinho.")
        self.status = QComboBox()
        for val, lab in [("ativo", "Somente ativos"), (None, "Todos os status")] + C.CHARACTER_STATUS[1:]:
            self.status.addItem(lab, val)
        self.status.currentIndexChanged.connect(lambda _=None: self.reload())
        hl.addWidget(self.status)
        root.addWidget(head)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "Personagem", "Jogador", "XP", "Ciclo"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 34)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 220)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selected)
        root.addWidget(self.table, 3)

        # -- ajuste individual
        box = QGroupBox("Personagem selecionado")
        bl = QVBoxLayout(box)
        self.sel_label = QLabel("Selecione um personagem na lista.")
        bl.addWidget(self.sel_label)
        row = QHBoxLayout()
        self.step_buttons = []
        for text, delta in (("−10", -10), ("−5", -5), ("+5", 5), ("+10", 10)):
            b = button(text, slot=lambda d=delta: self._delta(d))
            self.step_buttons.append(b)
            row.addWidget(b)
        self.custom = QSpinBox()
        self.custom.setRange(-100, 100)
        self.custom.setValue(15)
        self.custom.setPrefix("Δ ")
        self.custom.setSuffix(" %")
        row.addWidget(self.custom)
        self.b_custom = button("Aplicar", slot=lambda: self._delta(self.custom.value()))
        row.addWidget(self.b_custom)
        row.addSpacing(16)
        self.set_value = QSpinBox()
        self.set_value.setRange(0, 100)
        self.set_value.setSuffix(" %")
        row.addWidget(self.set_value)
        self.b_set = button("Definir", slot=self._set)
        row.addWidget(self.b_set)
        row.addStretch()
        bl.addLayout(row)
        row2 = QHBoxLayout()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Motivo (opcional, aparece no histórico)")
        self.reason.setMaxLength(xp.MAX_REASON)
        row2.addWidget(self.reason, 1)
        self.b_reset = button("Zerar", slot=lambda: self._simple("reset"))
        self.b_complete = button("Completar (100%)", slot=lambda: self._simple("complete"))
        self.b_cycle = button("Novo ciclo", "primary", lambda: self._simple("cycle"))
        for b in (self.b_reset, self.b_complete, self.b_cycle):
            row2.addWidget(b)
        bl.addLayout(row2)
        root.addWidget(box)

        # -- alteração coletiva + histórico
        low = QHBoxLayout()
        bulk = QGroupBox("Alteração coletiva (itens marcados na lista)")
        bk = QHBoxLayout(bulk)
        self.bulk_amount = QSpinBox()
        self.bulk_amount.setRange(1, 100)
        self.bulk_amount.setValue(10)
        self.bulk_amount.setSuffix(" %")
        bk.addWidget(self.bulk_amount)
        bk.addWidget(button("Aumentar", slot=lambda: self._bulk(1)))
        bk.addWidget(button("Reduzir", slot=lambda: self._bulk(-1)))
        bk.addWidget(button("Marcar todos", slot=self._check_all))
        low.addWidget(bulk)
        root.addLayout(low)

        hist_box = QGroupBox("Histórico do personagem selecionado")
        hv = QVBoxLayout(hist_box)
        self.history = DataTable([("Quando", 140), ("De → Para", 110), ("Variação", 80), ("Origem", 100), ("Motivo", 0)])
        self.history.setMaximumHeight(190)
        hv.addWidget(self.history)
        root.addWidget(hist_box)
        self._toggle(False)

    # -- dados
    def _toggle(self, on: bool):
        for w in (*self.step_buttons, self.b_custom, self.b_set, self.b_reset, self.b_complete, self.b_cycle,
                  self.custom, self.set_value, self.reason):
            w.setEnabled(on)

    def reload(self) -> None:
        keep = self.current_id()
        with db.session() as s:
            q = s.query(Character).filter_by(campaign_id=self.ctx.campaign_id).options(selectinload(Character.player))
            if self.status.currentData():
                q = q.filter_by(status=self.status.currentData())
            chars = q.order_by(Character.name).all()
            data = [(c.id, c.name, c.player.display_name, c.xp_percent, c.xp_cycle, c.status) for c in chars]
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(data))
        target = None
        for r, (cid, name, player, pct, cycle, status) in enumerate(data):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Unchecked)
            check.setData(Qt.UserRole, cid)
            self.table.setItem(r, 0, check)
            for col, text in ((1, name + ("" if status == "ativo" else f"  ({C.label(C.CHARACTER_STATUS, status)})")),
                              (2, player), (4, str(cycle))):
                it = QTableWidgetItem(text)
                it.setData(Qt.UserRole, cid)
                self.table.setItem(r, col, it)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(pct)
            bar.setFormat("%p%" + ("  ✦ marco completo" if pct == 100 else ""))
            self.table.setCellWidget(r, 3, bar)
            self.table.item(r, 1).setData(Qt.UserRole, cid)
            if cid == keep:
                target = r
        self.table.blockSignals(False)
        if target is not None:
            self.table.selectRow(target)
        self._selected()

    def current_id(self) -> int | None:
        r = self.table.currentRow()
        if r < 0 or self.table.item(r, 1) is None:
            return None
        return self.table.item(r, 1).data(Qt.UserRole)

    def select(self, cid: int) -> None:
        self.reload()
        for r in range(self.table.rowCount()):
            if self.table.item(r, 1).data(Qt.UserRole) == cid:
                self.table.selectRow(r)
                return

    def _selected(self):
        cid = self.current_id()
        self._toggle(cid is not None)
        if cid is None:
            self.sel_label.setText("Selecione um personagem na lista.")
            self.history.fill([])
            return
        with db.session() as s:
            c = s.get(Character, cid)
            self.sel_label.setText(f"<b>{c.name}</b> — {c.xp_percent}% · ciclo {c.xp_cycle}")
            self.set_value.setValue(c.xp_percent)
            hist = (s.query(ExperienceHistory).filter_by(character_id=cid).order_by(ExperienceHistory.id.desc()).limit(60).all())
            rows = [(h.id, [fmt_datetime(h.created_at), f"{h.previous_percent}% → {h.new_percent}%", f"{h.delta:+d}",
                            ORIGIN.get(h.origin, h.origin), h.reason or ""], None) for h in hist]
        self.history.fill(rows)

    # -- ações
    def _apply(self, fn):
        cid = self.current_id()
        if cid is None:
            return
        reason = self.reason.text()

        def go(s, user):
            return fn(s, crud.get_owned(s, Character, cid, user.id), reason)
        ok, result = attempt(self, self.call, go)
        if ok:
            self.reason.clear()
            self.info(xp.describe(result))
            self.changed()
            self.select(cid)

    def _delta(self, delta: int):
        self._apply(lambda s, c, r: xp.apply_delta(s, c, delta, r))

    def _set(self):
        value = self.set_value.value()
        self._apply(lambda s, c, r: xp.set_percent(s, c, value, r))

    def _simple(self, what: str):
        fn = {"reset": xp.reset, "complete": xp.complete, "cycle": xp.start_new_cycle}[what]
        self._apply(lambda s, c, r: fn(s, c, r))

    def _check_all(self):
        n = self.table.rowCount()
        every = all(self.table.item(r, 0).checkState() == Qt.Checked for r in range(n))
        for r in range(n):
            self.table.item(r, 0).setCheckState(Qt.Unchecked if every else Qt.Checked)

    def _bulk(self, sign: int):
        ids = [self.table.item(r, 0).data(Qt.UserRole) for r in range(self.table.rowCount())
               if self.table.item(r, 0).checkState() == Qt.Checked]
        if not ids:
            self.info("Marque ao menos um personagem na lista.")
            return
        amount, reason = self.bulk_amount.value() * sign, self.reason.text()
        ok, results = attempt(self, self.call, lambda s, u: xp.apply_bulk(s, self.ctx.campaign_id, ids, amount, reason))
        if ok:
            self.reason.clear()
            self.info("Alteração coletiva aplicada: " + "; ".join(xp.describe(r) for r in results))
            self.changed()
