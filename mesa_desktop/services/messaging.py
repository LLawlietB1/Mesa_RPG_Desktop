"""Mensagens para jogadores: monta o texto (somente dados públicos, nunca anotações do mestre) e entrega por
(1) links de WhatsApp/SMS que abrem no computador/celular do mestre (sem custo) ou
(2) envio direto via Twilio (opcional; precisa de credenciais nas configurações e de conta liberada)."""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from sqlalchemy.orm import Session

from mesa_desktop.models import CharacterItem, GameSession, MessageLog, Player, Quest, utcnow

MAX_BODY = 1500
DEFAULT_COUNTRY_CODE = "55"

KINDS = [
    ("personagem", "Ficha resumida e XP dos personagens do jogador"),
    ("inventario", "Inventário dos personagens do jogador"),
    ("proxima_sessao", "Aviso da próxima sessão"),
    ("sessao_resumo", "Resumo da última sessão"),
    ("missoes", "Missões em andamento e objetivos"),
    ("livre", "Mensagem livre"),
]


class PhoneError(ValueError):
    pass


def normalize_phone(raw: str, default_cc: str | None = None) -> str:
    """Converte para E.164 (+5511999998888). Números de 10-11 dígitos recebem o código do país padrão."""
    if default_cc is None:
        from mesa_desktop import paths
        default_cc = str(paths.load_settings().get("country_code") or DEFAULT_COUNTRY_CODE)
    text = (raw or "").strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        raise PhoneError("Informe um telefone.")
    if text.startswith("+"):
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    elif len(digits) in (10, 11):
        digits = default_cc + digits
    if not 10 <= len(digits) <= 15:
        raise PhoneError("Telefone inválido. Use DDD + número (ex.: 11 99999-8888) ou o formato internacional +55…")
    return "+" + digits


def wa_link(phone: str, text: str) -> str:
    return f"https://wa.me/{phone.lstrip('+')}?text={urllib.parse.quote(text)}"


def sms_link(phone: str, text: str) -> str:
    return f"sms:{phone}?body={urllib.parse.quote(text)}"


def _fmt_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def build_text(s: Session, kind: str, player: Player, campaign, extra: str = "") -> str | None:
    """Texto para um jogador; None quando não há nada a enviar a ele nesta categoria."""
    cid = campaign.id
    head = f"Olá, {player.display_name}! ({campaign.name})\n"
    body: list[str] = []
    chars = [c for c in player.characters if c.campaign_id == cid and c.status == "ativo"]
    if kind == "personagem":
        if not chars:
            return None
        for c in chars:
            info = " ".join(x for x in (c.race, c.char_class) if x)
            lvl = f", nível {c.level}" if c.level is not None else ""
            body.append(f"• {c.name}{(' — ' + info) if info else ''}{lvl}\n  XP: {c.xp_percent}%"
                        + (" ✦ marco completo!" if c.xp_percent == 100 else ""))
    elif kind == "inventario":
        rows = []
        for c in chars:
            held = s.query(CharacterItem).filter_by(character_id=c.id).all()
            if held:
                rows.append(f"• {c.name}: " + ", ".join(f"{h.item.name} ×{h.quantity}" for h in held))
        if not rows:
            return None
        body = rows
    elif kind == "proxima_sessao":
        nxt = (s.query(GameSession).filter(GameSession.campaign_id == cid, GameSession.status == "agendada",
                                           GameSession.date >= date.today()).order_by(GameSession.date).first())
        if nxt is None:
            return None
        body.append(f"Próxima sessão: #{nxt.number} — {nxt.title}\nData: {_fmt_date(nxt.date)}")
        last = (s.query(GameSession).filter(GameSession.campaign_id == cid, GameSession.status == "realizada")
                .order_by(GameSession.number.desc()).first())
        if last and last.pending:
            body.append("Pendências da última sessão:\n" + last.pending.strip())
    elif kind == "sessao_resumo":
        last = (s.query(GameSession).filter(GameSession.campaign_id == cid, GameSession.status == "realizada")
                .order_by(GameSession.number.desc()).first())
        if last is None or not (last.summary or last.pending):
            return None
        body.append(f"Resumo da sessão #{last.number} — {last.title} ({_fmt_date(last.date)}):")
        if last.summary:
            body.append(last.summary.strip())
        if last.pending:
            body.append("Pendências:\n" + last.pending.strip())
    elif kind == "missoes":
        quests = (s.query(Quest).filter(Quest.campaign_id == cid, Quest.status.in_(["em_andamento", "disponivel"]))
                  .order_by(Quest.title).all())
        if not quests:
            return None
        for q in quests:
            lines = [f"• {q.title}" + (f" (prazo {_fmt_date(q.deadline)})" if q.deadline else "")]
            lines += [f"   {'✔' if o.done else '○'} {o.description}" for o in q.objectives]
            body.append("\n".join(lines))
    elif kind == "livre":
        pass
    else:
        raise ValueError("Tipo de mensagem desconhecido.")
    if extra.strip():
        body.append(extra.strip().replace("{jogador}", player.display_name).replace("{campanha}", campaign.name))
    if not body:
        return None
    return (head + "\n" + "\n\n".join(body))[:MAX_BODY]


# ---------------------------------------------------------------- envio direto (Twilio)

def server_channels(cfg: dict) -> dict[str, bool]:
    base = bool(cfg.get("account_sid") and cfg.get("auth_token"))
    return {"sms": base and bool(cfg.get("sms_from")), "whatsapp": base and bool(cfg.get("whatsapp_from"))}


def sent_last_24h(s: Session, owner_id: int) -> int:
    return s.query(MessageLog).filter(MessageLog.owner_id == owner_id,
                                      MessageLog.created_at >= utcnow() - timedelta(days=1)).count()


class SendError(Exception):
    pass


def send_via_twilio(cfg: dict, channel: str, to_phone: str, body: str) -> str:
    if not server_channels(cfg).get(channel):
        raise SendError("Envio direto não está configurado para este canal (Configurações → Mensagens).")
    sender = cfg["sms_from"] if channel == "sms" else cfg["whatsapp_from"]
    if channel == "whatsapp":
        to_phone = "whatsapp:" + to_phone
        sender = sender if sender.startswith("whatsapp:") else "whatsapp:" + sender
    url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg['account_sid']}/Messages.json"
    payload = urllib.parse.urlencode({"To": to_phone, "From": sender, "Body": body}).encode()
    auth = base64.b64encode(f"{cfg['account_sid']}:{cfg['auth_token']}".encode()).decode()
    req = urllib.request.Request(url, data=payload, headers={"Authorization": f"Basic {auth}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:      # noqa: S310 (URL fixa https)
            return json.loads(resp.read()).get("sid", "")
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read()).get("message", "")
        except (ValueError, OSError):
            msg = ""
        raise SendError(f"O provedor recusou o envio: {msg or exc.code}"[:280]) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SendError("Não foi possível falar com o provedor de mensagens. Tente novamente.") from None


def log_message(s: Session, owner_id: int, player_id: int | None, channel: str, ok: bool,
                provider_id: str = "", error: str = "", chars: int = 0) -> None:
    s.add(MessageLog(owner_id=owner_id, player_id=player_id, channel=channel, ok=ok,
                     provider_id=provider_id or None, error=(error or None), chars=chars))
    s.commit()
