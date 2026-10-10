from __future__ import annotations

from sqlalchemy.orm import selectinload

from mesa_desktop import constants as C
from mesa_desktop import db
from mesa_desktop.models import NPC, Character, GameSession, Quest
from mesa_desktop.services import crud
from mesa_desktop.ui.kit import F, ListDetailPage, ask_text, attempt, confirm, h, kv, link, para, section
from mesa_desktop.ui.theme import badge_html
from mesa_desktop.utils import fmt_date, fmt_datetime, like_pattern

STATUS_OPTS = [(None, "Todos os status")] + C.QUEST_STATUS


class QuestsPage(ListDetailPage):
    title = "Missões"
    new_label = "Nova missão"
    needs_campaign = True
    search_hint = "Buscar no título ou descrição…"
    empty_text = "Nenhuma missão cadastrada nesta campanha."
    columns = [("Título", 0), ("Objetivos", 90), ("Prazo", 100), ("Status", 110)]
    filters = [("status", "Status", STATUS_OPTS)]

    def subtitle(self):
        return "Missões, objetivos e histórico de status."

    def extra_actions(self):
        return [("Mudar status…", self._status)]

    def rows(self, s, q, flt):
        query = s.query(Quest).filter_by(campaign_id=self.ctx.campaign_id).options(selectinload(Quest.objectives))
        if q:
            pat = like_pattern(q)
            query = query.filter(Quest.title.ilike(pat, escape="\\") | Quest.description.ilike(pat, escape="\\"))
        if flt["status"]:
            query = query.filter_by(status=flt["status"])
        out = []
        for x in query.order_by(Quest.updated_at.desc()):
            done = sum(1 for o in x.objectives if o.done)
            out.append((x.id, [x.title, f"{done}/{len(x.objectives)}" if x.objectives else "—", fmt_date(x.deadline),
                               C.label(C.QUEST_STATUS, x.status)], x.status))
        return out

    def detail_html(self, s, qid):
        x = crud.get_owned(s, Quest, qid, self.ctx.user_id)
        body = [f"<h1>{h(x.title)}</h1>", badge_html(x.status, C.label(C.QUEST_STATUS, x.status))]
        body.append(kv([("NPC", h(x.npc.name) if x.npc else "—"), ("Prazo", h(fmt_date(x.deadline))),
                        ("Personagens", h(", ".join(c.name for c in x.characters) or "—"))]))
        if x.description:
            body.append(section("Descrição", f"<p>{para(x.description)}</p>"))
        if x.rewards:
            body.append(section("Recompensas previstas", f"<p>{para(x.rewards)}</p>"))
        if x.master_notes:
            body.append(section("Observações privadas", f"<p>{para(x.master_notes)}</p>"))
        rows = "".join(
            f"<tr><td>{link('toggle', '☑' if o.done else '☐', o.id)}</td>"
            f"<td>{'<s>' + h(o.description) + '</s>' if o.done else h(o.description)}</td>"
            f"<td>{link('rmobj', 'remover', o.id, danger=True)}</td></tr>" for o in x.objectives)
        body.append(section("Objetivos", f"<table>{rows or '<tr><td class=muted>Nenhum objetivo.</td></tr>'}</table>"
                            f"<p>{link('addobj', '＋ Adicionar objetivo')}</p>"))
        sessions = s.query(GameSession).filter(GameSession.quests.any(Quest.id == x.id)).order_by(GameSession.number.desc()).all()
        if sessions:
            body.append(section("Sessões", "<p>" + ", ".join(f"#{g.number} {h(g.title)}" for g in sessions) + "</p>"))
        body.append(section("Histórico de status", "<table>" + "".join(
            f"<tr><td class='muted'>{fmt_datetime(e.created_at)}</td>"
            f"<td>{h(C.label(C.QUEST_STATUS, e.old_status) if e.old_status else '—')} → {h(C.label(C.QUEST_STATUS, e.new_status))}</td></tr>"
            for e in x.status_history) + "</table>"))
        return "".join(body), {}

    def on_link(self, action, arg):
        qid = self.table.current_id()
        if qid is None:
            return
        if action == "addobj":
            text = ask_text(self, "Novo objetivo", "Descreva o objetivo (até 300 caracteres):")
            if text and attempt(self, self.call, lambda s, u: crud.add_objective(s, u.id, qid, text))[0]:
                self.changed()
                self.select(qid)
        elif action == "toggle":
            if attempt(self, self.call, lambda s, u: crud.toggle_objective(s, u.id, int(arg)))[0]:
                self.reload()
        elif action == "rmobj":
            if attempt(self, self.call, lambda s, u: crud.delete_objective(s, u.id, int(arg)))[0]:
                self.reload()

    def _fields(self, s):
        cid = self.ctx.campaign_id
        return [
            F("title", "Título", required=True),
            F("status", "Status", "choice", C.QUEST_STATUS),
            F("npc_id", "NPC responsável / relacionado", "choice",
              [(n.id, n.name) for n in s.query(NPC).filter_by(campaign_id=cid).order_by(NPC.name)], blank="— nenhum —"),
            F("deadline", "Prazo", "date"),
            F("characters", "Personagens relacionados", "multi",
              [(c.id, c.name) for c in crud.campaign_characters(s, cid)]),
            F("description", "Descrição", "multiline", height=110),
            F("rewards", "Recompensas previstas", "multiline", hint="Apenas registro: não altera fichas nem inventários."),
            F("master_notes", "Observações privadas", "multiline"),
        ]

    def on_new(self):
        with db.session() as s:
            fields = self._fields(s)
        res = self.do_form("Nova missão", fields, {"status": "planejada"},
                           lambda v: self.call(lambda s, u: crud.save_quest(s, u.id, self.ctx.campaign_id, v).id), width=620)
        if res:
            self.changed()
            self.select(res)

    def on_edit(self, qid):
        with db.session() as s:
            fields = self._fields(s)
            x = crud.get_owned(s, Quest, qid, self.ctx.user_id)
            vals = {k: getattr(x, k) for k in ("title", "status", "npc_id", "deadline", "description", "rewards", "master_notes")}
            vals["characters"] = [c.id for c in x.characters]
        res = self.do_form("Editar missão", fields, vals,
                           lambda v: self.call(lambda s, u: crud.save_quest(
                               s, u.id, self.ctx.campaign_id, v, crud.get_owned(s, Quest, qid, u.id)).id), width=620)
        if res:
            self.changed()
            self.select(qid)

    def on_delete(self, qid):
        if confirm(self, "Excluir esta missão e seus objetivos?", danger=True):
            if attempt(self, self.call, lambda s, u: crud.delete_quest(s, u.id, qid))[0]:
                self.changed()

    def _status(self, qid):
        with db.session() as s:
            current = s.get(Quest, qid).status
        status = self.choose("Status da missão", "Novo status:", C.QUEST_STATUS, current)
        if status and attempt(self, self.call, lambda s, u: crud.set_quest_status(s, u.id, qid, status))[0]:
            self.changed()
            self.select(qid)
