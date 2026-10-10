from __future__ import annotations

from sqlalchemy.orm import joinedload

from mesa_desktop import constants as C
from mesa_desktop import db
from mesa_desktop.models import NPC, CharacterNPCRelationship, GameSession, Quest
from mesa_desktop.services import crud, images
from mesa_desktop.ui.kit import F, ListDetailPage, attempt, confirm, h, kv, link, para, section
from mesa_desktop.ui.theme import badge_html
from mesa_desktop.utils import like_pattern

STATUS_OPTS = [(None, "Todos os status")] + C.NPC_STATUS


class NPCsPage(ListDetailPage):
    title = "NPCs"
    new_label = "Novo NPC"
    needs_campaign = True
    search_hint = "Buscar por nome, apelido ou descrição…"
    empty_text = "Nenhum NPC cadastrado nesta campanha."
    columns = [("Nome", 0), ("Apelido", 130), ("Status", 110)]
    filters = [("status", "Status", STATUS_OPTS)]

    def subtitle(self):
        return "Personagens não jogáveis e suas relações com o grupo."

    def rows(self, s, q, flt):
        query = s.query(NPC).filter_by(campaign_id=self.ctx.campaign_id)
        if q:
            pat = like_pattern(q)
            query = query.filter(NPC.name.ilike(pat, escape="\\") | NPC.nickname.ilike(pat, escape="\\")
                                 | NPC.description.ilike(pat, escape="\\"))
        if flt["status"]:
            query = query.filter_by(status=flt["status"])
        return [(n.id, [n.name, n.nickname or "—", C.label(C.NPC_STATUS, n.status)], n.status) for n in query.order_by(NPC.name)]

    def detail_html(self, s, nid):
        n = crud.get_owned(s, NPC, nid, self.ctx.user_id)
        pics = {}
        body = [f"<h1>{h(n.name)}</h1>", badge_html(n.status, C.label(C.NPC_STATUS, n.status))]
        if n.nickname:
            body.append(f'<p class="muted">«{h(n.nickname)}»</p>')
        if n.image:
            data = images.image_bytes(s, self.ctx.user_id, n.image)
            if data:
                pics["img:npc"] = data
                body.append('<p><img src="img:npc"></p>')
        for label, text in (("Descrição", n.description), ("Aparência", n.appearance), ("Personalidade", n.personality),
                            ("Objetivos", n.goals), ("Motivação", n.motivation), ("Segredos", n.secrets),
                            ("Observações privadas", n.master_notes)):
            if text:
                body.append(section(label, f"<p>{para(text)}</p>"))
        rels = (s.query(CharacterNPCRelationship).filter_by(npc_id=n.id)
                .options(joinedload(CharacterNPCRelationship.character)).order_by(CharacterNPCRelationship.id).all())
        rows = "".join(f"<tr><td>{h(r.character.name)}</td><td>{h(C.label(C.NPC_RELATIONS, r.kind))}</td>"
                       f"<td class='muted'>{h(r.description or '')}</td><td>{link('rmrel', 'remover', r.id, danger=True)}</td></tr>"
                       for r in rels)
        body.append(section("Relações com personagens",
                            f"<table>{rows or '<tr><td class=muted>Nenhuma relação.</td></tr>'}</table>"
                            f"<p>{link('addrel', '＋ Registrar relação')}</p>"))
        quests = s.query(Quest).filter_by(npc_id=n.id).order_by(Quest.title).all()
        if quests:
            body.append(section("Missões ligadas", "<p>" + ", ".join(h(q.title) for q in quests) + "</p>"))
        sessions = s.query(GameSession).filter(GameSession.npcs.any(NPC.id == n.id)).order_by(GameSession.number.desc()).all()
        if sessions:
            body.append(section("Sessões em que aparece", "<p>" + ", ".join(f"#{x.number} {h(x.title)}" for x in sessions) + "</p>"))
        return "".join(body), pics

    def on_link(self, action, arg):
        nid = self.table.current_id()
        if nid is None:
            return
        if action == "addrel":
            with db.session() as s:
                chars = [(c.id, c.name) for c in crud.campaign_characters(s, self.ctx.campaign_id)]
            if not chars:
                self.info("Esta campanha ainda não tem personagens.")
                return
            self.do_form("Registrar relação", [
                F("character_id", "Personagem", "choice", chars, required=True),
                F("kind", "Tipo de relação", "choice", C.NPC_RELATIONS),
                F("description", "Detalhes"),
            ], {"kind": "neutro"}, lambda v: self.call(lambda s, u: crud.add_relationship(
                s, u.id, nid, v["character_id"], v["kind"], v["description"])), width=480)
            self.refresh_detail()
        elif action == "rmrel":
            if attempt(self, self.call, lambda s, u: crud.delete_relationship(s, u.id, int(arg)))[0]:
                self.refresh_detail()

    def _fields(self, can_img, image=None):
        return [
            F("name", "Nome", required=True), F("nickname", "Apelido"),
            F("status", "Status", "choice", C.NPC_STATUS),
            F("image", "Imagem", "image", image_bytes=image, image_enabled=can_img),
            F("description", "Descrição", "multiline"), F("appearance", "Aparência", "multiline"),
            F("personality", "Personalidade", "multiline"), F("goals", "Objetivos", "multiline"),
            F("motivation", "Motivação", "multiline"), F("secrets", "Segredos", "multiline"),
            F("master_notes", "Observações privadas", "multiline"),
        ]

    def on_new(self):
        res = self.do_form("Novo NPC", self._fields(self.ctx.user.can_upload_images), {"status": "ativo"},
                           lambda v: self.call(lambda s, u: crud.save_npc(s, u, self.ctx.campaign_id, v).id),
                           intro="Registre o NPC agora; você decide depois como ele entra na história.", width=620)
        if res:
            self.changed()
            self.select(res)

    def on_edit(self, nid):
        with db.session() as s:
            n = crud.get_owned(s, NPC, nid, self.ctx.user_id)
            vals = {k: getattr(n, k) for k in ("name", "nickname", "status", "description", "appearance", "personality",
                                               "goals", "motivation", "secrets", "master_notes")}
            img = images.image_bytes(s, self.ctx.user_id, n.image)
        res = self.do_form("Editar NPC", self._fields(self.ctx.user.can_upload_images, img), vals,
                           lambda v: self.call(lambda s, u: crud.save_npc(
                               s, u, self.ctx.campaign_id, v, crud.get_owned(s, NPC, nid, u.id)).id), width=620)
        if res:
            self.changed()
            self.select(nid)

    def on_delete(self, nid):
        if confirm(self, "Excluir este NPC?", danger=True):
            if attempt(self, self.call, lambda s, u: crud.delete_npc(s, u.id, nid))[0]:
                self.changed()
