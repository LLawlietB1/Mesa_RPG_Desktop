from __future__ import annotations

from mesa_desktop import constants as C
from mesa_desktop import db
from mesa_desktop.models import Campaign, Character, Note, Player
from mesa_desktop.services import crud
from mesa_desktop.ui.kit import F, ListDetailPage, attempt, confirm, h, kv, link, para
from mesa_desktop.utils import fmt_datetime, like_pattern

CAT_OPTS = [(None, "Todas as categorias")] + C.NOTE_CATEGORIES
ARCH_OPTS = [("nao", "Ativas"), ("sim", "Arquivadas"), ("todas", "Todas")]
SCOPE_OPTS = [("atual", "Campanha atual"), ("todas", "Todas as campanhas")]


class NotesPage(ListDetailPage):
    title = "Notas"
    new_label = "Nova nota"
    needs_campaign = True
    search_hint = "Buscar no título ou conteúdo…"
    empty_text = "Nenhuma nota. Elas ficam visíveis só para você."
    columns = [("★", 30), ("Título", 0), ("Categoria", 170), ("Atualizada", 130)]
    filters = [("category", "Categoria", CAT_OPTS), ("archived", "Arquivo", ARCH_OPTS), ("scope", "Escopo", SCOPE_OPTS)]

    def subtitle(self):
        return "Anotações privadas do mestre."

    def extra_actions(self):
        return [("Alternar ★ importante", lambda i: self._toggle(i, "important")),
                ("Arquivar / desarquivar", lambda i: self._toggle(i, "archived"))]

    def rows(self, s, q, flt):
        query = s.query(Note).join(Campaign, Campaign.id == Note.campaign_id).filter(Campaign.owner_id == self.ctx.user_id)
        if flt["scope"] != "todas":
            query = query.filter(Note.campaign_id == self.ctx.campaign_id)
        if q:
            pat = like_pattern(q)
            query = query.filter(Note.title.ilike(pat, escape="\\") | Note.content.ilike(pat, escape="\\"))
        if flt["category"]:
            query = query.filter(Note.category == flt["category"])
        if flt["archived"] == "nao":
            query = query.filter(Note.archived.is_(False))
        elif flt["archived"] == "sim":
            query = query.filter(Note.archived.is_(True))
        notes = query.order_by(Note.important.desc(), Note.updated_at.desc()).all()
        return [(n.id, ["★" if n.important else "", n.title + ("  (arquivada)" if n.archived else ""),
                        C.label(C.NOTE_CATEGORIES, n.category), fmt_datetime(n.updated_at)], None) for n in notes]

    def detail_html(self, s, nid):
        n = crud.get_owned(s, Note, nid, self.ctx.user_id)
        rel = []
        if n.character:
            rel.append(("Personagem", h(n.character.name)))
        if n.player:
            rel.append(("Jogador", h(n.player.display_name)))
        return (f"<h1>{'★ ' if n.important else ''}{h(n.title)}</h1>"
                f'<p class="muted">{h(C.label(C.NOTE_CATEGORIES, n.category))} · {h(n.campaign.name)} · '
                f'atualizada {fmt_datetime(n.updated_at)}{" · arquivada" if n.archived else ""}</p>'
                + (kv(rel) if rel else "") + f"<p>{para(n.content)}</p>"), {}

    def _fields(self, s):
        cid = self.ctx.campaign_id
        chars = [(c.id, c.name) for c in crud.campaign_characters(s, cid)]
        players = [(p.id, p.display_name) for p in crud.my_players(s, self.ctx.user_id)]
        return [
            F("title", "Título", required=True),
            F("category", "Categoria", "choice", C.NOTE_CATEGORIES),
            F("character_id", "Personagem relacionado", "choice", chars, blank="— nenhum —"),
            F("player_id", "Jogador relacionado", "choice", players, blank="— nenhum —",
              hint="Se escolher um personagem, o jogador responsável é usado."),
            F("content", "Conteúdo", "multiline", required=True, height=170),
            F("important", "Importante", "check"), F("archived", "Arquivada", "check"),
        ]

    def on_new(self):
        with db.session() as s:
            fields = self._fields(s)
        res = self.do_form("Nova nota privada", fields, {"category": "outros"},
                           lambda v: self.call(lambda s, u: crud.save_note(s, u.id, self.ctx.campaign_id, v).id), width=620)
        if res:
            self.changed()
            self.select(res)

    def on_edit(self, nid):
        with db.session() as s:
            fields = self._fields(s)
            n = crud.get_owned(s, Note, nid, self.ctx.user_id)
            vals = {k: getattr(n, k) for k in ("title", "category", "character_id", "player_id", "content", "important", "archived")}
            campaign_id = n.campaign_id
        res = self.do_form("Editar nota", fields, vals,
                           lambda v: self.call(lambda s, u: crud.save_note(
                               s, u.id, campaign_id, v, crud.get_owned(s, Note, nid, u.id)).id), width=620)
        if res:
            self.changed()
            self.select(nid)

    def on_delete(self, nid):
        if confirm(self, "Excluir esta nota?", danger=True):
            if attempt(self, self.call, lambda s, u: crud.delete_note(s, u.id, nid))[0]:
                self.changed()

    def _toggle(self, nid, flag):
        if attempt(self, self.call, lambda s, u: crud.toggle_note(s, u.id, nid, flag))[0]:
            self.changed()
            self.select(nid)
