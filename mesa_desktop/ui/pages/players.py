from __future__ import annotations

from sqlalchemy.orm import selectinload

from mesa_desktop import constants as C
from mesa_desktop import db
from mesa_desktop.models import Campaign, CampaignPlayer, Character, Player
from mesa_desktop.services import crud
from mesa_desktop.ui.kit import F, ListDetailPage, attempt, confirm, h, kv, link, para, section
from mesa_desktop.ui.theme import badge_html
from mesa_desktop.utils import fmt_datetime

STATUS_OPTS = [(None, "Todos os status")] + C.PLAYER_STATUS


class PlayersPage(ListDetailPage):
    title = "Jogadores"
    new_label = "Novo jogador"
    search_hint = "Buscar por nome, apelido ou nome real…"
    empty_text = "Nenhum jogador cadastrado. Clique em «Novo jogador»."
    columns = [("Nome", 0), ("Contato", 150), ("Personagens", 100), ("Status", 100)]
    filters = [("status", "Status", STATUS_OPTS)]

    def subtitle(self):
        return "Pessoas da sua mesa. Só o nome é obrigatório; contato e consentimento são opcionais."

    def extra_actions(self):
        return [("Mudar status…", self._status), ("Enviar mensagem…", self._message)]

    def rows(self, s, q, flt):
        players = (crud.my_players(s, self.ctx.user_id, q, flt["status"] or ""))
        counts = {p.id: s.query(Character).filter_by(player_id=p.id).count() for p in players}
        out = []
        for p in players:
            contact = "—" if not p.phone else p.phone + ("" if p.messaging_consent else " (sem consent.)")
            out.append((p.id, [p.display_name, contact, str(counts[p.id]), C.label(C.PLAYER_STATUS, p.status)], p.status))
        return out

    def detail_html(self, s, pid):
        p = crud.get_owned(s, Player, pid, self.ctx.user_id)
        chars = (s.query(Character).filter_by(player_id=p.id).options(selectinload(Character.campaign))
                 .order_by(Character.name).all())
        member = (s.query(CampaignPlayer, Campaign).join(Campaign, Campaign.id == CampaignPlayer.campaign_id)
                  .filter(CampaignPlayer.player_id == p.id).order_by(CampaignPlayer.joined_at.desc()).all())
        phone = h(p.phone or "—")
        if p.phone and not p.messaging_consent:
            phone += ' <span class="muted">(sem consentimento para mensagens)</span>'
        body = [f"<h1>{h(p.display_name)}</h1>", badge_html(p.status, C.label(C.PLAYER_STATUS, p.status)),
                f'<p class="muted">Cadastrado em {fmt_datetime(p.created_at)}</p>',
                kv([("Nome real", h(p.real_name or "—")), ("Apelido", h(p.nickname or "—")),
                    ("E-mail", h(p.email or "—")), ("Telefone", phone)])]
        if p.notes:
            body.append(section("Observações", f"<p>{para(p.notes)}</p>"))
        body.append(section("Personagens", "<table>" + "".join(
            f"<tr><td>{h(c.name)}</td><td class='muted'>{h(c.campaign.name)}</td><td>{c.xp_percent}%</td>"
            f"<td>{badge_html(c.status, C.label(C.CHARACTER_STATUS, c.status))}</td></tr>" for c in chars) + "</table>"
            if chars else '<p class="muted">Nenhum personagem.</p>'))
        body.append(section("Histórico de participação", "<table>" + "".join(
            f"<tr><td>{h(c.name)}</td><td class='muted'>desde {fmt_datetime(m.joined_at)}</td>"
            f"<td>{'ativo' if m.status == 'ativo' else 'saiu em ' + fmt_datetime(m.left_at)}</td></tr>"
            for m, c in member) + "</table>" if member else '<p class="muted">Ainda não participa de campanhas.</p>'))
        return "".join(body), {}

    def _fields(self):
        return [
            F("display_name", "Nome de exibição", required=True),
            F("real_name", "Nome real"), F("nickname", "Apelido"), F("email", "E-mail"),
            F("phone", "Telefone / WhatsApp", hint="Com DDD (ex.: 11 99999-8888). Usado só para você enviar mensagens a este jogador."),
            F("messaging_consent", "Consentimento", "check", hint="O jogador concordou em receber mensagens da mesa neste telefone."),
            F("status", "Status", "choice", C.PLAYER_STATUS),
            F("notes", "Observações administrativas", "multiline"),
        ]

    def on_new(self):
        res = self.do_form("Novo jogador", self._fields(), {"status": "ativo"},
                           lambda v: self.call(lambda s, u: crud.save_player(s, u.id, v).id))
        if res:
            self.changed()
            self.select(res)

    def on_edit(self, pid):
        with db.session() as s:
            p = crud.get_owned(s, Player, pid, self.ctx.user_id)
            vals = {k: getattr(p, k) for k in ("display_name", "real_name", "nickname", "email", "phone",
                                               "messaging_consent", "status", "notes")}
        res = self.do_form("Editar jogador", self._fields(), vals,
                           lambda v: self.call(lambda s, u: crud.save_player(s, u.id, v, crud.get_owned(s, Player, pid, u.id)).id))
        if res:
            self.changed()
            self.select(pid)

    def on_delete(self, pid):
        if not confirm(self, "Excluir este jogador? (Quem tem personagens não pode ser excluído: arquive-o.)", danger=True):
            return
        if attempt(self, self.call, lambda s, u: crud.delete_player(s, u.id, s.get(Player, pid)))[0]:
            self.changed()

    def _status(self, pid):
        with db.session() as s:
            current = s.get(Player, pid).status
        status = self.choose("Status do jogador", "Novo status:", C.PLAYER_STATUS, current)
        if status and attempt(self, self.call, lambda s, u: crud.set_player_status(s, u.id, s.get(Player, pid), status))[0]:
            self.changed()

    def _message(self, pid):
        self.win.goto("messages", preselect=pid)
