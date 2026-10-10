from __future__ import annotations

from sqlalchemy import func

from mesa_desktop import constants as C
from mesa_desktop import db
from mesa_desktop.models import NPC, Campaign, Character, GameSession, Player, Quest
from mesa_desktop.services import crud, images
from mesa_desktop.ui.kit import F, ListDetailPage, ask_text, attempt, confirm, h, kv, link, para, section
from mesa_desktop.ui.theme import badge_html
from mesa_desktop.utils import fmt_date, format_kv_lines

STATUS_OPTS = [(None, "Todos os status")] + C.CAMPAIGN_STATUS


class CampaignsPage(ListDetailPage):
    title = "Campanhas"
    new_label = "Nova campanha"
    search_hint = "Buscar campanha pelo nome…"
    empty_text = "Nenhuma campanha ainda. Clique em «Nova campanha»."
    columns = [("Nome", 0), ("Sistema", 130), ("Personagens", 100), ("Status", 100)]
    filters = [("status", "Status", STATUS_OPTS)]

    def subtitle(self):
        return "Cada campanha é independente: jogadores, personagens, notas, sessões, NPCs, missões e itens."

    def extra_actions(self):
        return [("Usar como campanha atual", self._use), ("Mudar status…", self._status)]

    # -- lista
    def rows(self, s, q, flt):
        camps = crud.my_campaigns(s, self.ctx.user_id, q, flt["status"] or "")
        counts = dict(s.query(Character.campaign_id, func.count(Character.id)).group_by(Character.campaign_id).all())
        out = []
        for c in camps:
            mark = "★ " if c.id == self.ctx.campaign_id else ""
            out.append((c.id, [mark + c.name, c.system or "—", str(counts.get(c.id, 0)), C.label(C.CAMPAIGN_STATUS, c.status)], c.status))
        return out

    # -- detalhe
    def detail_html(self, s, cid):
        c = crud.get_owned(s, Campaign, cid, self.ctx.user_id)
        members = crud.campaign_members(s, c.id, only_active=False)
        chars = crud.campaign_characters(s, c.id)
        stats = {
            "Personagens": len(chars),
            "Sessões": s.query(GameSession).filter_by(campaign_id=c.id).count(),
            "Missões": s.query(Quest).filter_by(campaign_id=c.id).count(),
            "NPCs": s.query(NPC).filter_by(campaign_id=c.id).count(),
        }
        pics = {}
        body = [f"<h1>{h(c.name)}</h1>", badge_html(c.status, C.label(C.CAMPAIGN_STATUS, c.status))]
        if c.id == self.ctx.campaign_id:
            body.append(' &nbsp;<span class="muted">★ campanha atual</span>')
        if c.cover_image:
            data = images.image_bytes(s, self.ctx.user_id, c.cover_image)
            if data:
                pics["img:cover"] = data
                body.append('<p><img src="img:cover"></p>')
        body.append(kv([("Sistema", h(c.system or "—")), ("Ambientação", h(c.setting or "—")),
                        ("Início", h(fmt_date(c.start_date))),
                        ("Resumo", " · ".join(f"{k}: <b>{v}</b>" for k, v in stats.items()))]))
        if c.description:
            body.append(section("Descrição", f"<p>{para(c.description)}</p>"))
        if c.settings:
            body.append(section("Configurações específicas", kv([(k, h(v)) for k, v in c.settings.items()])))
        if c.notes:
            body.append(section("Observações gerais", f"<p>{para(c.notes)}</p>"))
        rows = []
        for p, m in members:
            tag = "" if m.status == "ativo" else ' <span class="muted">(saiu)</span>'
            act = link("rmplayer", "remover", p.id, danger=True) if m.status == "ativo" else ""
            rows.append(f"<tr><td>{h(p.display_name)}{tag}</td><td>{act}</td></tr>")
        body.append(section("Jogadores", f"<table>{''.join(rows) or '<tr><td class=muted>Nenhum jogador.</td></tr>'}</table>"
                            f"<p>{link('addplayer', '＋ Adicionar jogador')}</p>"))
        if chars:
            body.append(section("Personagens", "<table>" + "".join(
                f"<tr><td>{h(ch.name)}</td><td class='muted'>{h(ch.player.display_name)}</td>"
                f"<td>{ch.xp_percent}%</td><td>{badge_html(ch.status, C.label(C.CHARACTER_STATUS, ch.status))}</td></tr>"
                for ch in chars) + "</table>"))
        recent = (s.query(GameSession).filter_by(campaign_id=c.id)
                  .order_by(GameSession.date.desc(), GameSession.number.desc()).limit(5).all())
        if recent:
            body.append(section("Sessões recentes", "<table>" + "".join(
                f"<tr><td>#{x.number}</td><td>{h(x.title)}</td><td class='muted'>{fmt_date(x.date)}</td></tr>" for x in recent) + "</table>"))
        return "".join(body), pics

    # -- ações
    def on_link(self, action, arg):
        cid = self.table.current_id()
        if cid is None:
            return
        if action == "addplayer":
            def pick(s, user):
                taken = {p.id for p, _ in crud.campaign_members(s, cid)}
                return [(p.id, p.display_name) for p in crud.my_players(s, user.id)
                        if p.status != "arquivado" and p.id not in taken]
            ok, options = attempt(self, self.call, pick)
            if not ok:
                return
            if not options:
                self.info("Todos os jogadores já participam (ou cadastre um novo em «Jogadores»).")
                return
            player_id = self.choose("Adicionar jogador", "Jogador:", options)
            if player_id and attempt(self, self.call, lambda s, u: crud.add_player_to_campaign(s, u.id, cid, player_id))[0]:
                self.changed()
        elif action == "rmplayer":
            if confirm(self, "Encerrar a participação deste jogador? O histórico e os personagens são mantidos."):
                if attempt(self, self.call, lambda s, u: crud.remove_player_from_campaign(s, u.id, cid, int(arg)))[0]:
                    self.changed()

    def _use(self, cid):
        self.ctx.set_campaign(cid)
        self.info("Campanha atual alterada.")

    def _status(self, cid):
        with db.session() as s:
            current = s.get(Campaign, cid).status
        status = self.choose("Status da campanha", "Novo status:", C.CAMPAIGN_STATUS, current)
        if status and attempt(self, self.call, lambda s, u: crud.set_campaign_status(s, u.id, s.get(Campaign, cid), status))[0]:
            self.changed()

    # -- formulários
    def _fields(self, can_img: bool, cover: bytes | None = None):
        return [
            F("name", "Nome da campanha", required=True),
            F("status", "Status", "choice", C.CAMPAIGN_STATUS),
            F("system", "Sistema de RPG"), F("setting", "Ambientação"),
            F("start_date", "Data de início", "date"),
            F("description", "Descrição", "multiline"),
            F("notes", "Observações gerais", "multiline"),
            F("settings_text", "Configurações específicas", "multiline",
              hint="Uma por linha, no formato «chave: valor» (ex.: Marco de XP: a cada 3 sessões)."),
            F("cover", "Imagem de capa", "image", image_bytes=cover, image_enabled=can_img),
        ]

    def on_new(self):
        result = self.do_form("Nova campanha", self._fields(self.ctx.user.can_upload_images),
                              {"status": "planejada"},
                              lambda v: self.call(lambda s, u: crud.save_campaign(s, u, v).id),
                              intro="Cada campanha é independente das outras.")
        if result:
            self.ctx.set_campaign(result, notify=False)
            self.changed()
            self.select(result)

    def on_edit(self, cid):
        with db.session() as s:
            c = crud.get_owned(s, Campaign, cid, self.ctx.user_id)
            vals = {k: getattr(c, k) for k in ("name", "status", "system", "setting", "start_date", "description", "notes")}
            vals["settings_text"] = format_kv_lines(c.settings)
            cover = images.image_bytes(s, self.ctx.user_id, c.cover_image)
        res = self.do_form("Editar campanha", self._fields(self.ctx.user.can_upload_images, cover), vals,
                           lambda v: self.call(lambda s, u: crud.save_campaign(s, u, v, crud.get_owned(s, Campaign, cid, u.id)).id))
        if res:
            self.changed()
            self.select(cid)

    def on_delete(self, cid):
        with db.session() as s:
            name = s.get(Campaign, cid).name
        typed = ask_text(self, "Excluir campanha",
                         f"Isto apaga a campanha e TODOS os seus registros.\nDigite o nome exato para confirmar:\n«{name}»")
        if typed is None:
            return
        if attempt(self, self.call, lambda s, u: crud.delete_campaign(s, u.id, s.get(Campaign, cid), typed))[0]:
            self.changed()
