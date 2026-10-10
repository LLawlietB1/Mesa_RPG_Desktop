from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout
from sqlalchemy.orm import selectinload

from mesa_desktop import constants as C
from mesa_desktop import db
from mesa_desktop.models import NPC, Character, GameSession, Quest, SessionEvent
from mesa_desktop.services import crud
from mesa_desktop.ui.kit import Detail, F, ListDetailPage, ask_text, attempt, confirm, h, kv, link, para, section
from mesa_desktop.ui.theme import badge_html
from mesa_desktop.utils import fmt_date, fmt_datetime, like_pattern

STATUS_OPTS = [(None, "Todos os status")] + C.SESSION_STATUS
ORDER_OPTS = [("recentes", "Mais recentes"), ("antigas", "Mais antigas")]


class SessionsPage(ListDetailPage):
    title = "Sessões"
    new_label = "Nova sessão"
    needs_campaign = True
    search_hint = "Buscar no título, resumo, pendências ou acontecimentos…"
    empty_text = "Nenhuma sessão registrada nesta campanha."
    columns = [("Nº", 50), ("Título", 0), ("Data", 100), ("Status", 100)]
    filters = [("status", "Status", STATUS_OPTS), ("order", "Ordem", ORDER_OPTS)]

    def subtitle(self):
        return "Diário de sessões da campanha: " + (self.ctx.campaign_name() or "—")

    def extra_actions(self):
        return [("Linha do tempo…", lambda _id: self._timeline())]

    def rows(self, s, q, flt):
        query = s.query(GameSession).filter_by(campaign_id=self.ctx.campaign_id)
        if q:
            pat = like_pattern(q)
            query = query.filter(GameSession.title.ilike(pat, escape="\\") | GameSession.summary.ilike(pat, escape="\\")
                                 | GameSession.pending.ilike(pat, escape="\\")
                                 | GameSession.events.any(SessionEvent.description.ilike(pat, escape="\\")))
        if flt["status"]:
            query = query.filter_by(status=flt["status"])
        asc = flt["order"] == "antigas"
        query = query.order_by(GameSession.number.asc() if asc else GameSession.number.desc())
        return [(x.id, [str(x.number), x.title, fmt_date(x.date), C.label(C.SESSION_STATUS, x.status)], x.status)
                for x in query.all()]

    def detail_html(self, s, sid):
        x = crud.get_owned(s, GameSession, sid, self.ctx.user_id)
        events = (s.query(SessionEvent).filter_by(session_id=x.id).options(selectinload(SessionEvent.character))
                  .order_by(SessionEvent.id).all())
        body = [f"<h1>#{x.number} — {h(x.title)}</h1>", badge_html(x.status, C.label(C.SESSION_STATUS, x.status)),
                f'<p class="muted">{fmt_date(x.date)}</p>']
        if x.participants:
            body.append(section("Personagens participantes", "<p>" + ", ".join(h(c.name) for c in x.participants) + "</p>"))
        if x.npcs:
            body.append(section("NPCs envolvidos", "<p>" + ", ".join(h(n.name) for n in x.npcs) + "</p>"))
        if x.quests:
            body.append(section("Missões relacionadas", "<p>" + ", ".join(h(q.title) for q in x.quests) + "</p>"))
        if x.summary:
            body.append(section("Resumo", f"<p>{para(x.summary)}</p>"))
        if x.pending:
            body.append(section("Pendências para a próxima sessão", f"<p>{para(x.pending)}</p>"))
        if x.master_notes:
            body.append(section("Observações privadas do mestre", f"<p>{para(x.master_notes)}</p>"))
        rows = "".join(
            f"<tr><td>{h(e.description)}"
            + (f" <span class='muted'>— {h(e.character.name)}</span>" if e.character else "")
            + f"</td><td>{link('rmevent', 'remover', e.id, danger=True)}</td></tr>" for e in events)
        body.append(section("Acontecimentos importantes",
                            f"<table>{rows or '<tr><td class=muted>Nenhum acontecimento registrado.</td></tr>'}</table>"
                            f"<p>{link('addevent', '＋ Registrar acontecimento')}</p>"))
        return "".join(body), {}

    def on_link(self, action, arg):
        sid = self.table.current_id()
        if sid is None:
            return
        if action == "addevent":
            with db.session() as s:
                chars = [(c.id, c.name) for c in crud.campaign_characters(s, self.ctx.campaign_id)]
            self.do_form("Registrar acontecimento", [
                F("description", "Acontecimento", "multiline", required=True),
                F("character_id", "Personagem relacionado", "choice", chars, blank="— ninguém em especial —"),
            ], None, lambda v: self.call(lambda s, u: crud.add_session_event(
                s, u.id, sid, v["description"], v["character_id"])), width=520)
            self.refresh_detail()
        elif action == "rmevent":
            if attempt(self, self.call, lambda s, u: crud.delete_session_event(s, u.id, int(arg)))[0]:
                self.refresh_detail()

    def _choices(self, s):
        cid = self.ctx.campaign_id
        return ([(c.id, c.name) for c in crud.campaign_characters(s, cid)],
                [(n.id, n.name) for n in s.query(NPC).filter_by(campaign_id=cid).order_by(NPC.name)],
                [(q.id, q.title) for q in s.query(Quest).filter_by(campaign_id=cid).order_by(Quest.title)])

    def _fields(self, s):
        chars, npcs, quests = self._choices(s)
        return [
            F("number", "Nº da sessão", "int", required=True, minimum=1, maximum=9999),
            F("title", "Título", required=True),
            F("date", "Data", "date", required=True),
            F("status", "Status", "choice", C.SESSION_STATUS),
            F("summary", "Resumo", "multiline", height=110),
            F("pending", "Pendências para a próxima sessão", "multiline"),
            F("master_notes", "Observações privadas do mestre", "multiline"),
            F("participants", "Personagens participantes", "multi", chars),
            F("npcs", "NPCs envolvidos", "multi", npcs),
            F("quests", "Missões relacionadas", "multi", quests),
        ]

    def on_new(self):
        with db.session() as s:
            fields = self._fields(s)
            number = crud.next_session_number(s, self.ctx.campaign_id)
        res = self.do_form("Nova sessão", fields, {"number": number, "date": date.today(), "status": "agendada"},
                           lambda v: self.call(lambda s, u: crud.save_session(s, u.id, self.ctx.campaign_id, v).id), width=640)
        if res:
            self.changed()
            self.select(res)

    def on_edit(self, sid):
        with db.session() as s:
            fields = self._fields(s)
            x = crud.get_owned(s, GameSession, sid, self.ctx.user_id)
            vals = {k: getattr(x, k) for k in ("number", "title", "date", "status", "summary", "pending", "master_notes")}
            vals.update(participants=[c.id for c in x.participants], npcs=[n.id for n in x.npcs],
                        quests=[q.id for q in x.quests])
        res = self.do_form(f"Editar sessão {vals['number']}", fields, vals,
                           lambda v: self.call(lambda s, u: crud.save_session(
                               s, u.id, self.ctx.campaign_id, v, crud.get_owned(s, GameSession, sid, u.id)).id), width=640)
        if res:
            self.changed()
            self.select(sid)

    def on_delete(self, sid):
        if confirm(self, "Excluir esta sessão e seus acontecimentos?", danger=True):
            if attempt(self, self.call, lambda s, u: crud.delete_session(s, u.id, s.get(GameSession, sid)))[0]:
                self.changed()

    def _timeline(self):
        with db.session() as s:
            sessions = (s.query(GameSession).filter_by(campaign_id=self.ctx.campaign_id)
                        .options(selectinload(GameSession.events).selectinload(SessionEvent.character))
                        .order_by(GameSession.date, GameSession.number).all())
            parts = []
            for x in sessions:
                events = "".join(
                    f"<li>{h(e.description)}" + (f" <span class='muted'>— {h(e.character.name)}</span>" if e.character else "")
                    + "</li>" for e in x.events)
                parts.append(f"<h2>{fmt_date(x.date)} · #{x.number} {h(x.title)} "
                             f"{badge_html(x.status, C.label(C.SESSION_STATUS, x.status))}</h2>"
                             + (f"<p>{para(x.summary)}</p>" if x.summary else "")
                             + (f"<ul>{events}</ul>" if events else ""))
        dlg = QDialog(self)
        dlg.setWindowTitle("Linha do tempo — " + self.ctx.campaign_name())
        dlg.resize(720, 560)
        lay = QVBoxLayout(dlg)
        view = Detail()
        view.show_html("".join(parts) or '<p class="muted">Nenhuma sessão ainda.</p>')
        lay.addWidget(view)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(dlg.reject)
        box.button(QDialogButtonBox.Close).setText("Fechar")
        lay.addWidget(box)
        dlg.exec()
