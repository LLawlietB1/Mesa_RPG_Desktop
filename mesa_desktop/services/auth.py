"""Autenticação compatível com o app web: Argon2id para senha e palavra-chave de recuperação (os mesmos hashes,
então a mesma conta entra nos dois programas), bloqueio por tentativas e recuperação sem e-mail."""
from __future__ import annotations

import functools
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete
from sqlalchemy.orm import Session

from mesa_desktop.models import Campaign, FileAsset, Player, User, UserSession, utcnow
from mesa_desktop.services.errors import AppError

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 10
LOCKED_MSG = "Muitas tentativas. Aguarde alguns minutos e tente novamente."
_ph = PasswordHasher()


@functools.cache
def _dummy_hash() -> str:
    return _ph.hash("senha-ficticia-para-igualar-tempo")


def hash_secret(value: str) -> str:
    return _ph.hash(value)


def verify_secret(hashed: str | None, value: str) -> bool:
    if not hashed:
        return False
    try:
        return _ph.verify(hashed, value)
    except (VerificationError, InvalidHashError):
        return False


def hash_passphrase(p: str) -> str:
    return hash_secret(p.strip().lower())


def verify_passphrase(hashed: str | None, p: str) -> bool:
    return verify_secret(hashed, p.strip().lower())


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def check_email(email: str) -> str:
    try:
        return validate_email(email, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise AppError("E-mail inválido.") from None


def password_problem(pw: str) -> str | None:
    if len(pw) < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    if len(pw) > 200:
        return "A senha é longa demais."
    if not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
        return "A senha deve ter letras e números."
    return None


def passphrase_problem(p: str) -> str | None:
    if len((p or "").strip()) < 6:
        return "A palavra-chave deve ter pelo menos 6 caracteres."
    return None


def register_user(s: Session, name: str, email: str, password: str, passphrase: str) -> User:
    """Cria a conta. A primeira conta de um banco vazio vira administradora (como no app web)."""
    name = (name or "").strip()
    if not name:
        raise AppError("Informe o seu nome.")
    email = check_email(email)
    if s.query(User.id).filter_by(email=email).first():
        raise AppError("Já existe uma conta com este e-mail.")
    for problem in (password_problem(password), passphrase_problem(passphrase)):
        if problem:
            raise AppError(problem)
    first = s.query(User.id).first() is None
    user = User(name=name[:120], email=email, password_hash=hash_secret(password),
                recovery_hash=hash_passphrase(passphrase), role="ADMIN" if first else "MESTRE")
    s.add(user)
    s.commit()
    return user


def _locked(user: User) -> bool:
    return bool(user.locked_until and user.locked_until > utcnow())


def _register_failure(s: Session, user: User) -> None:
    failed = (user.failed_logins or 0) + 1
    if failed >= MAX_FAILED_LOGINS:
        user.failed_logins, user.locked_until = 0, utcnow() + timedelta(minutes=LOCK_MINUTES)
    else:
        user.failed_logins = failed
    s.commit()


def authenticate(s: Session, email: str, password: str) -> User:
    """Devolve o usuário ou levanta AppError (mensagem idêntica para e-mail/senha errados)."""
    generic = AppError("E-mail ou senha incorretos.")
    user = s.query(User).filter_by(email=normalize_email(email)).first()
    if user is None:
        verify_secret(_dummy_hash(), password)
        raise generic
    if _locked(user):
        raise AppError(LOCKED_MSG)
    if not verify_secret(user.password_hash, password):
        _register_failure(s, user)
        raise generic
    user.failed_logins, user.locked_until = 0, None
    s.commit()
    return user


def reset_password_with_passphrase(s: Session, email: str, passphrase: str, new_password: str) -> None:
    generic = AppError("E-mail ou palavra-chave incorretos.")
    user = s.query(User).filter_by(email=normalize_email(email)).first()
    if user is None or not user.recovery_hash:
        verify_secret(_dummy_hash(), passphrase)
        raise generic
    if _locked(user):
        raise AppError(LOCKED_MSG)
    if not verify_passphrase(user.recovery_hash, passphrase):
        _register_failure(s, user)
        raise generic
    problem = password_problem(new_password)
    if problem:
        raise AppError(problem)
    user.password_hash = hash_secret(new_password)
    user.failed_logins, user.locked_until = 0, None
    s.query(UserSession).filter_by(user_id=user.id).delete()      # encerra as sessões da versão web
    s.commit()


def change_password(s: Session, user: User, current: str, new: str) -> None:
    if not verify_secret(user.password_hash, current):
        raise AppError("Senha atual incorreta.")
    problem = password_problem(new)
    if problem:
        raise AppError(problem)
    user.password_hash = hash_secret(new)
    s.query(UserSession).filter_by(user_id=user.id).delete()
    s.commit()


def change_recovery(s: Session, user: User, current: str, passphrase: str) -> None:
    if not verify_secret(user.password_hash, current):
        raise AppError("Senha atual incorreta.")
    problem = passphrase_problem(passphrase)
    if problem:
        raise AppError(problem)
    user.recovery_hash = hash_passphrase(passphrase)
    s.commit()


def end_web_sessions(s: Session, user: User) -> int:
    """Encerra os logins da versão web (cookies) desta conta."""
    n = s.query(UserSession).filter_by(user_id=user.id).delete()
    s.commit()
    return n


def web_session_count(s: Session, user: User) -> int:
    return s.query(UserSession).filter(UserSession.user_id == user.id, UserSession.expires_at > utcnow()).count()


def request_images(s: Session, user: User, cooldown_min: int = 30) -> str:
    """Registra o pedido de liberação de imagens (o administrador aprova na tela Administração)."""
    if user.can_upload_images:
        return "O envio de imagens já está liberado para a sua conta."
    if user.images_requested_at and utcnow() - user.images_requested_at < timedelta(minutes=cooldown_min):
        return "Você já pediu a liberação há pouco. Aguarde um pouco antes de pedir de novo."
    user.images_requested_at = utcnow()
    s.commit()
    return "Pedido registrado. Um administrador poderá liberar na tela Administração."


def delete_account(s: Session, user: User, current: str, confirm_text: str) -> None:
    if not verify_secret(user.password_hash, current):
        raise AppError("Senha atual incorreta.")
    if confirm_text.strip().upper() != "EXCLUIR":
        raise AppError("Digite EXCLUIR para confirmar.")
    uid = user.id
    for model in (Campaign, Player, FileAsset):           # campanhas primeiro: personagens referenciam jogadores
        s.execute(delete(model).where(model.owner_id == uid))
    s.execute(delete(User).where(User.id == uid))
    s.commit()
