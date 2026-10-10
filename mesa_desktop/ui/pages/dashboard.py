from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from sqlalchemy.orm import selectinload

from mesa_desktop import constants as C
from mesa_desktop import db
from mesa_desktop.models import (Campaign, CampaignPlayer, Character, GameSession, Note, Player, Quest, SessionEvent)
from mesa_desktop.ui.kit import Detail, Page, bar_html, button, h, link, page_header, para, section
from mesa_desktop.ui.theme import ACCENT_STRONG, SURFACE2, TEXT2, badge_html
from mesa_desktop.utils import fmt_date, fmt_datetime


class DashboardPage(Page):
    title = "Painel"
    needs_campaign = True

    def __init__(self, ctx, window):
        super().__init__(ctx, window)
        root = QVBoxLayout(self)
        head, hl = page_header("Painel", "")
        hl.addWidget(button("＋ Nova campanha", slot=lambda: window.goto("campaigns", new=True)))
        root.addWidget(head)
        self.view = Detail()
        self.view.action.connect(self._link)
        root.addWidget(self.view, 1)

    def _link(self, action, arg):
        if action == "goto":
            self.win.goto(arg)
        elif action == "character":
            self.win.goto("characters", select=int(arg))

    def reload(self) -> None:
        cid = self.ctx.campaign_id
        with db.session() as s:
            c = s.get(Campaign, cid)
            if c is None:
                self.view.placeholder("Nenhuma campanha selecionada.")
                return
            players = (s.query(Player).join(CampaignPlayer)
                       .filter(CampaignPlayer.campaign_id == cid, CampaignPlayer.status == "ativo", Player.status == "ativo").count())
            party = (s.query(Character).filter_by(campaign_id=cid, status="ativo").options(selectinload(Character.player))
                     .order_by(Character.name).all())
            quests = s.query(Quest).filter_by(campaign_id=cid, status="em_andamento").count()
            total = s.query(Campaign).filter_by(owner_id=self.ctx.user_id).count()
            nxt = (s.query(GameSession).filter(GameSession.campaign_id == cid, GameSession.status == "agendada",
                                               GameSession.date >= date.today()).order_by(GameSession.date, GameSession.number).first())
            notes = (s.query(Note).filter_by(campaign_id=cid, archived=False)
                     .order_by(Note.important.desc(), Note.updated_at.desc()).limit(5).all())
            events = (s.query(SessionEvent).filter_by(campaign_id=cid).options(selectinload(SessionEvent.session),
                                                                              selectinload(SessionEvent.character))
                      .order_by(SessionEvent.id.desc()).limit(6).all())
            stats = [("Campanhas", total), ("Jogadores ativos", players), ("Personagens ativos", len(party)),
                     ("Missões em andamento", quests)]
            cells = "".join(f'<td align="center" bgcolor="{SURFACE2}" width="25%"><span style="font-size:20pt;color:{ACCENT_STRONG}">'
                            f'<b>{n}</b></span><br><span style="color:{TEXT2}">{h(lab)}</span></td>' for lab, n in stats)
            body = [f"<h1>{h(c.name)}</h1>", badge_html(c.status, C.label(C.CAMPAIGN_STATUS, c.status)),
                    f' <span class="muted">{h(c.system or "")}</span>',
                    f'<table width="100%" cellspacing="8"><tr>{cells}</tr></table>']
            body.append(section("Próxima sessão",
                                f"<p><b>#{nxt.number} — {h(nxt.title)}</b> · {fmt_date(nxt.date)}</p>" if nxt else
                                f'<p class="muted">Nenhuma sessão agendada. {link("goto", "Agendar uma sessão", "sessions")}</p>'))
            body.append(section("Grupo (XP)", "<table>" + "".join(
                f"<tr><td>{link('character', ch.name, ch.id)}</td><td class='muted'>{h(ch.player.display_name)}</td>"
                f"<td>{bar_html(ch.xp_percent, 180)}</td></tr>" for ch in party) + "</table>"
                if party else f'<p class="muted">Nenhum personagem ativo. {link("goto", "Criar personagem", "characters")}</p>'))
            body.append(section("Notas em destaque", "<table>" + "".join(
                f"<tr><td>{'★ ' if n.important else ''}{h(n.title)}</td><td class='muted'>{fmt_datetime(n.updated_at)}</td></tr>"
                for n in notes) + "</table>" if notes else '<p class="muted">Nenhuma nota.</p>'))
            body.append(section("Acontecimentos recentes", "<table>" + "".join(
                f"<tr><td>{h(e.description)}</td><td class='muted'>sessão #{e.session.number}"
                f"{' · ' + h(e.character.name) if e.character else ''}</td></tr>" for e in events) + "</table>"
                if events else '<p class="muted">Nenhum acontecimento registrado.</p>'))
        self.view.show_html("".join(body))
