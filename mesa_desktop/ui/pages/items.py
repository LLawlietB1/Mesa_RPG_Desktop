from __future__ import annotations

from sqlalchemy.orm import joinedload, selectinload

from mesa_desktop import constants as C
from mesa_desktop import db
from mesa_desktop.models import CharacterItem, Item, Quest
from mesa_desktop.services import crud
from mesa_desktop.ui.kit import F, ListDetailPage, attempt, confirm, h, link, para, section
from mesa_desktop.utils import like_pattern

CAT_OPTS = [(None, "Todas as categorias")] + C.ITEM_CATEGORIES


class ItemsPage(ListDetailPage):
    title = "Inventário"
    new_label = "Novo item"
    needs_campaign = True
    search_hint = "Buscar no nome ou descrição…"
    empty_text = "Nenhum item registrado nesta campanha."
    columns = [("Item", 0), ("Categoria", 130), ("Qtd. total", 80)]
    filters = [("category", "Categoria", CAT_OPTS)]

    def subtitle(self):
        return "Moedas, tesouros, equipamentos e quem os possui."

    def rows(self, s, q, flt):
        query = s.query(Item).filter_by(campaign_id=self.ctx.campaign_id).options(selectinload(Item.holdings))
        if q:
            pat = like_pattern(q)
            query = query.filter(Item.name.ilike(pat, escape="\\") | Item.description.ilike(pat, escape="\\"))
        if flt["category"]:
            query = query.filter_by(category=flt["category"])
        return [(i.id, [i.name, C.label(C.ITEM_CATEGORIES, i.category), str(sum(x.quantity for x in i.holdings))], None)
                for i in query.order_by(Item.name)]

    def detail_html(self, s, iid):
        i = crud.get_owned(s, Item, iid, self.ctx.user_id)
        holds = (s.query(CharacterItem).filter_by(item_id=i.id)
                 .options(joinedload(CharacterItem.character), joinedload(CharacterItem.quest)).order_by(CharacterItem.id).all())
        body = [f"<h1>{h(i.name)}</h1>", f'<p class="muted">{h(C.label(C.ITEM_CATEGORIES, i.category))}</p>']
        if i.description:
            body.append(f"<p>{para(i.description)}</p>")
        if i.notes:
            body.append(section("Observações", f"<p>{para(i.notes)}</p>"))
        rows = "".join(
            f"<tr><td><b>{h(x.character.name)}</b></td><td>×{x.quantity}</td>"
            f"<td class='muted'>{h(x.origin or '')}{' · missão: ' + h(x.quest.title) if x.quest else ''}</td>"
            f"<td>{link('rmhold', 'remover', x.id, danger=True)}</td></tr>" for x in holds)
        body.append(section("Quem possui", f"<table>{rows or '<tr><td class=muted>Sem dono (item do grupo).</td></tr>'}</table>"
                            f"<p>{link('addhold', '＋ Atribuir a um personagem')}</p>"))
        return "".join(body), {}

    def on_link(self, action, arg):
        iid = self.table.current_id()
        if iid is None:
            return
        if action == "addhold":
            with db.session() as s:
                chars = [(c.id, c.name) for c in crud.campaign_characters(s, self.ctx.campaign_id)]
                quests = [(q.id, q.title) for q in s.query(Quest).filter_by(campaign_id=self.ctx.campaign_id).order_by(Quest.title)]
            if not chars:
                self.info("Esta campanha ainda não tem personagens.")
                return
            self.do_form("Atribuir item", [
                F("character_id", "Personagem possuidor", "choice", chars, required=True),
                F("quantity", "Quantidade", "int", required=True, minimum=1, maximum=1000000),
                F("origin", "Origem / recompensa"),
                F("quest_id", "Missão relacionada", "choice", quests, blank="— nenhuma —"),
                F("notes", "Observações", "multiline"),
            ], {"quantity": 1}, lambda v: self.call(lambda s, u: crud.add_holding(
                s, u.id, iid, v["character_id"], v["quantity"], v["origin"], v["quest_id"], v["notes"])), width=500)
            self.reload()
        elif action == "rmhold":
            if attempt(self, self.call, lambda s, u: crud.delete_holding(s, u.id, int(arg)))[0]:
                self.reload()

    def _fields(self, s, creating: bool):
        base = [F("name", "Nome do item", required=True), F("category", "Categoria", "choice", C.ITEM_CATEGORIES),
                F("description", "Descrição", "multiline"), F("notes", "Observações", "multiline")]
        if creating:
            chars = [(c.id, c.name) for c in crud.campaign_characters(s, self.ctx.campaign_id)]
            quests = [(q.id, q.title) for q in s.query(Quest).filter_by(campaign_id=self.ctx.campaign_id).order_by(Quest.title)]
            base += [F("character_id", "Personagem possuidor (opcional)", "choice", chars, blank="— item do grupo / sem dono —"),
                     F("quantity", "Quantidade", "int", required=True, minimum=1, maximum=1000000,
                       hint="Só vale se você escolher um personagem."),
                     F("origin", "Origem / recompensa"),
                     F("quest_id", "Missão relacionada", "choice", quests, blank="— nenhuma —")]
        return base

    def on_new(self):
        with db.session() as s:
            fields = self._fields(s, True)
        res = self.do_form("Novo item", fields, {"category": "outro", "quantity": 1},
                           lambda v: self.call(lambda s, u: crud.save_item(s, u.id, self.ctx.campaign_id, v).id), width=560)
        if res:
            self.changed()
            self.select(res)

    def on_edit(self, iid):
        with db.session() as s:
            fields = self._fields(s, False)
            i = crud.get_owned(s, Item, iid, self.ctx.user_id)
            vals = {k: getattr(i, k) for k in ("name", "category", "description", "notes")}
        res = self.do_form("Editar item", fields, vals,
                           lambda v: self.call(lambda s, u: crud.save_item(
                               s, u.id, self.ctx.campaign_id, v, crud.get_owned(s, Item, iid, u.id)).id), width=560)
        if res:
            self.changed()
            self.select(iid)

    def on_delete(self, iid):
        if confirm(self, "Excluir este item e suas posses?", danger=True):
            if attempt(self, self.call, lambda s, u: crud.delete_item(s, u.id, iid))[0]:
                self.changed()
