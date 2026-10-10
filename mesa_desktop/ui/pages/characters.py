from __future__ import annotations

from sqlalchemy.orm import joinedload, selectinload

from mesa_desktop import constants as C
from mesa_desktop import db
from mesa_desktop.models import (Character, CharacterItem, CharacterNPCRelationship, ExperienceHistory, GameSession, Note,
                                 Player, Quest)
from mesa_desktop.services import crud, images
from mesa_desktop.ui.kit import F, ListDetailPage, attempt, bar_html, confirm, h, kv, link, para, section
from mesa_desktop.ui.theme import badge_html
from mesa_desktop.utils import fmt_date, fmt_datetime, format_kv_lines

STATUS_OPTS = [(None, "Todos os status")] + C.CHARACTER_STATUS
SORT_OPTS = [("nome", "Ordenar: nome"), ("xp", "Ordenar: XP"), ("nivel", "Ordenar: nível"), ("recentes", "Ordenar: recentes")]


class CharactersPage(ListDetailPage):
    title = "Personagens"
    new_label = "Novo personagem"
    needs_campaign = True
    search_hint = "Buscar personagem pelo nome…"
    empty_text = "Nenhum personagem nesta campanha."
    columns = [("Nome", 0), ("Jogador", 130), ("Classe", 110), ("Nível", 60), ("XP", 60), ("Status", 90)]
    filters = [("status", "Status", STATUS_OPTS), ("sort", "Ordem", SORT_OPTS)]

    def subtitle(self):
        return "Personagens da campanha atual: " + (self.ctx.campaign_name() or "—")

    def extra_actions(self):
        return [("Mudar status…", self._status), ("Ajustar XP…", lambda cid: self.win.goto("xp", select=cid))]

    def rows(self, s, q, flt):
        from mesa_desktop.utils import like_pattern
        query = s.query(Character).filter_by(campaign_id=self.ctx.campaign_id).options(selectinload(Character.player))
        if q:
            query = query.filter(Character.name.ilike(like_pattern(q), escape="\\"))
        if flt["status"]:
            query = query.filter_by(status=flt["status"])
        order = {"xp": Character.xp_percent.desc(), "nivel": Character.level.desc(), "recentes": Character.id.desc()}.get(
            flt["sort"], Character.name)
        return [(c.id, [c.name, c.player.display_name, c.char_class or "—",
                        "—" if c.level is None else str(c.level), f"{c.xp_percent}%", C.label(C.CHARACTER_STATUS, c.status)], c.status)
                for c in query.order_by(order, Character.name).all()]

    def detail_html(self, s, cid):
        c = crud.get_owned(s, Character, cid, self.ctx.user_id)
        pics = {}
        body = [f"<h1>{h(c.name)}</h1>", badge_html(c.status, C.label(C.CHARACTER_STATUS, c.status))]
        if c.portrait:
            data = images.image_bytes(s, self.ctx.user_id, c.portrait)
            if data:
                pics["img:portrait"] = data
                body.append('<p><img src="img:portrait"></p>')
        info = " · ".join(x for x in (c.race, c.char_class, f"nível {c.level}" if c.level is not None else None) if x)
        body.append(kv([("Jogador", h(c.player.display_name)), ("Ficha", h(info or "—")), ("Sistema", h(c.system or "—")),
                        ("XP", bar_html(c.xp_percent) + f' <span class="muted">ciclo {c.xp_cycle}</span>')]))
        for label, text in (("História", c.backstory), ("Personalidade", c.personality), ("Objetivos", c.goals),
                            ("Antecedentes", c.background)):
            if text:
                body.append(section(label, f"<p>{para(text)}</p>"))
        if c.extra:
            body.append(section("Atributos / campos do sistema", kv([(k, h(v)) for k, v in c.extra.items()])))
        if c.master_notes:
            body.append(section("Observações do mestre", f"<p>{para(c.master_notes)}</p>"))
        hist = (s.query(ExperienceHistory).filter_by(character_id=c.id).order_by(ExperienceHistory.id.desc()).limit(8).all())
        if hist:
            body.append(section("Últimas alterações de XP", "<table>" + "".join(
                f"<tr><td class='muted'>{fmt_datetime(x.created_at)}</td><td>{x.previous_percent}% → {x.new_percent}%</td>"
                f"<td>{h(x.reason or '')}</td></tr>" for x in hist) + "</table>"))
        items = s.query(CharacterItem).filter_by(character_id=c.id).options(joinedload(CharacterItem.item)).all()
        if items:
            body.append(section("Inventário", "<table>" + "".join(
                f"<tr><td>{h(i.item.name)}</td><td>×{i.quantity}</td><td class='muted'>{h(i.origin or '')}</td></tr>"
                for i in items) + "</table>"))
        quests = s.query(Quest).filter(Quest.characters.any(Character.id == c.id)).order_by(Quest.title).all()
        if quests:
            body.append(section("Missões", "<table>" + "".join(
                f"<tr><td>{h(q.title)}</td><td>{badge_html(q.status, C.label(C.QUEST_STATUS, q.status))}</td></tr>"
                for q in quests) + "</table>"))
        rels = (s.query(CharacterNPCRelationship).filter_by(character_id=c.id)
                .options(joinedload(CharacterNPCRelationship.npc)).all())
        if rels:
            body.append(section("Relações com NPCs", "<table>" + "".join(
                f"<tr><td>{h(r.npc.name)}</td><td>{h(C.label(C.NPC_RELATIONS, r.kind))}</td>"
                f"<td class='muted'>{h(r.description or '')}</td></tr>" for r in rels) + "</table>"))
        notes = s.query(Note).filter_by(character_id=c.id, archived=False).order_by(Note.updated_at.desc()).limit(5).all()
        if notes:
            body.append(section("Notas", "<table>" + "".join(f"<tr><td>{h(n.title)}</td></tr>" for n in notes) + "</table>"))
        sessions = (s.query(GameSession).filter(GameSession.participants.any(Character.id == c.id))
                    .order_by(GameSession.number.desc()).limit(8).all())
        if sessions:
            body.append(section("Sessões", "<table>" + "".join(
                f"<tr><td>#{x.number}</td><td>{h(x.title)}</td><td class='muted'>{fmt_date(x.date)}</td></tr>"
                for x in sessions) + "</table>"))
        return "".join(body), pics

    def _fields(self, players, can_img, portrait=None):
        return [
            F("name", "Nome do personagem", required=True),
            F("player_id", "Jogador responsável", "choice", [(p.id, p.display_name) for p in players], required=True,
              blank="Selecione…"),
            F("status", "Status", "choice", C.CHARACTER_STATUS),
            F("system", "Sistema de RPG"), F("race", "Raça / espécie"), F("char_class", "Classe / arquétipo"),
            F("level", "Nível", "int", minimum=0, maximum=999, hint="Opcional e sempre alterado manualmente."),
            F("portrait", "Retrato", "image", image_bytes=portrait, image_enabled=can_img),
            F("backstory", "História", "multiline"), F("personality", "Personalidade", "multiline"),
            F("goals", "Objetivos", "multiline"), F("background", "Antecedentes", "multiline"),
            F("master_notes", "Observações do mestre", "multiline"),
            F("extra_text", "Atributos / campos do sistema", "multiline",
              hint="Uma por linha, «chave: valor» (ex.: Força: 14). Adapte ao sistema da campanha."),
        ]

    def on_new(self):
        with db.session() as s:
            players = crud.player_choices(s, self.ctx.user_id)
            players = [type("P", (), {"id": p.id, "display_name": p.display_name}) for p in players]
        if not players:
            self.info("Cadastre um jogador antes de criar personagens.")
            self.win.goto("players")
            return
        from mesa_desktop.models import Campaign
        with db.session() as s:
            system = s.get(Campaign, self.ctx.campaign_id).system
        res = self.do_form(f"Novo personagem — {self.ctx.campaign_name()}", self._fields(players, self.ctx.user.can_upload_images),
                           {"status": "ativo", "system": system},
                           lambda v: self.call(lambda s, u: crud.save_character(s, u, self.ctx.campaign_id, v).id),
                           intro="Raça, classe, nível e atributos são opcionais e podem ser adaptados ao sistema da campanha.",
                           width=640)
        if res:
            self.changed()
            self.select(res)

    def on_edit(self, cid):
        with db.session() as s:
            c = crud.get_owned(s, Character, cid, self.ctx.user_id)
            players = [type("P", (), {"id": p.id, "display_name": p.display_name})
                       for p in crud.player_choices(s, self.ctx.user_id, c.player_id)]
            vals = {k: getattr(c, k) for k in ("name", "player_id", "status", "system", "race", "char_class", "level",
                                               "backstory", "personality", "goals", "background", "master_notes")}
            vals["extra_text"] = format_kv_lines(c.extra)
            portrait = images.image_bytes(s, self.ctx.user_id, c.portrait)
        res = self.do_form("Editar personagem", self._fields(players, self.ctx.user.can_upload_images, portrait), vals,
                           lambda v: self.call(lambda s, u: crud.save_character(
                               s, u, self.ctx.campaign_id, v, crud.get_owned(s, Character, cid, u.id)).id), width=640)
        if res:
            self.changed()
            self.select(cid)

    def on_delete(self, cid):
        if not confirm(self, "Excluir este personagem e todo o seu histórico de XP?", danger=True):
            return
        if attempt(self, self.call, lambda s, u: crud.delete_character(s, u.id, s.get(Character, cid)))[0]:
            self.changed()

    def _status(self, cid):
        with db.session() as s:
            current = s.get(Character, cid).status
        status = self.choose("Status do personagem", "Novo status:", C.CHARACTER_STATUS, current)
        if status and attempt(self, self.call, lambda s, u: crud.set_character_status(s, u.id, s.get(Character, cid), status))[0]:
            self.changed()
