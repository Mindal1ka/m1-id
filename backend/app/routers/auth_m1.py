"""M1 ID auth v2: реєстрація / вхід / сесії — у єдиному конверті
{ok, data, error}.

Модель сесій: ОДИН довгоживучий opaque-токен; у БД (таблиця sessions) лише
sha256-хеш токена + окремий публічний id для UI,
30 днів зі sliding-продовженням. Жодної ротації, reuse-detection,
grace-вікон чи in-memory кешів — вони й були джерелом «вильотів усіх
сесій» після кожного рестарту (кеш replay-пар живе в процесі; після
рестарту повтор живого токена виглядав крадіжкою → ревок усього).

Контракти ендпоінтів збережено (фронт сумісний без змін):
• register/login → {access_token, refresh_token, user} — обидва поля
  містять той самий сесійний токен (сумісність зі старим клієнтом);
• refresh → валідація + sliding-продовження, повертає ту саму пару
  (ідемпотентний, безпечний для паралельних вкладок і воркерів);
• logout / sessions / revoke / revoke-others — як раніше, кік за id.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.clock import naive_utcnow
from app.core.responses import ApiError, ok
from app.core.security import (
    create_session,
    dummy_verify,
    find_session,
    hash_password,
    hash_token,
    revoke_session,
    verify_password,
)
from app.db.models import RefreshSession, User
from app.deps import get_current_user, get_db
from app.schemas.auth import (
    LoginIn,
    LogoutIn,
    RefreshIn,
    RegisterIn,
    SessionRevokeIn,
    SessionsRevokeOthersIn,
)
from app.services.email_check import check_email
from app.services.ratelimit import (
    login_backoff_check,
    login_backoff_fail,
    login_backoff_reset,
    rate_limit,
)

router = APIRouter(prefix="/api/auth", tags=["M1 ID Auth"])


# ------------------------------------------------------------- helpers


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "email_verified": user.email_verified_at is not None,
    }


def _pair(db: Session, user: User, user_agent: str) -> dict:
    """Нова сесія → пара токенів. Обидва поля = той самий сесійний
    токен (клієнт очікує пару access+refresh; у v2 вони тотожні)."""
    token = create_session(db, user.id, user_agent)
    return {
        "access_token": token,
        "refresh_token": token,
        "user": _user_out(user),
    }


# --------------------------------------------------------------- роути


@router.post("/register", dependencies=[rate_limit(times=10)])
def register(body: RegisterIn, request: Request,
             db: Session = Depends(get_db)) -> dict:
    """Реєстрація акаунта M1 ID: username + password + email."""
    username = body.username.strip()
    email = body.email.strip().lower()

    # e-mail: синтаксис → одноразові домени → DNS MX
    valid, code = check_email(email)
    if not valid:
        raise ApiError(422, code, "email", code)

    # унікальність без урахування регістра
    dup_username = db.query(User.id).filter(
        func.lower(User.username) == username.lower()).first()
    if dup_username:
        raise ApiError(409, "username_taken", "username",
                       "username_already_exists")
    dup_email = db.query(User.id).filter(User.email == email).first()
    if dup_email:
        raise ApiError(409, "email_taken", "email",
                       "email_already_registered")

    user = User(
        username=username,
        username_lower=username.lower(),
        email=email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # гонка паралельних реєстрацій: check-then-insert вище пройшов,
        # унікальний індекс — остання інстанція. 409, а не 500.
        db.rollback()
        raise ApiError(409, "username_taken", "username",
                       "username_or_email_already_exists") from None

    return ok(_pair(db, user, request.headers.get("user-agent", "")))


@router.post("/login", dependencies=[rate_limit(times=10)])
def login(body: LoginIn, request: Request,
          db: Session = Depends(get_db)) -> dict:
    """Вхід за іменем АБО e-mail. Помилка — нейтральна (без підказок)."""
    login_value = body.login.strip().lower()
    login_backoff_check(login_value)
    user = (db.query(User)
            .filter((func.lower(User.username) == login_value)
                    | (User.email == login_value))
            .first())
    if user is None:
        # вирівнюємо час відповіді з гілкою «користувач є» (timing)
        dummy_verify(body.password)
        login_backoff_fail(login_value)
        raise ApiError(401, "invalid_credentials", "login",
                       "invalid_login_or_password")
    if not verify_password(user.password_hash, body.password):
        login_backoff_fail(login_value)
        raise ApiError(401, "invalid_credentials", "login",
                       "invalid_login_or_password")
    login_backoff_reset(login_value)
    return ok(_pair(db, user, request.headers.get("user-agent", "")))


@router.post("/refresh", dependencies=[rate_limit(times=60)])
def refresh(body: RefreshIn, request: Request,
            db: Session = Depends(get_db)) -> dict:
    """Ідемпотентне продовження сесії: токен живий → sliding-продовжуємо
    строк і повертаємо ту саму пару. Повторний виклик з тим самим токеном
    (інша вкладка, гонка після рестарту) — нормальний сценарій, 401 лише
    якщо сесію справді гасили/протухло."""
    token = body.refresh_token.strip()
    session = find_session(db, token)
    if session is None:
        raise ApiError(401, "refresh_invalid", "refresh_token",
                       "refresh_token_invalid_expired_or_revoked")
    now = naive_utcnow()
    user = db.get(User, session.user_id)
    if user is None:
        raise ApiError(401, "refresh_invalid", "refresh_token")

    # sliding: продовжуємо строк сесії на повний TTL. Пишемо в БД лише
    # коли це справді щось змінює (не на кожен виклик).
    ttl_days = get_settings().refresh_token_expire_days
    new_exp = now + timedelta(days=ttl_days)
    stale_seen = (session.last_seen_at is None
                  or now - session.last_seen_at > timedelta(hours=1))
    extend = (session.expires_at is None
              or new_exp - session.expires_at > timedelta(hours=1))
    if extend or stale_seen:
        if extend:
            session.expires_at = new_exp
        session.last_seen_at = now
        db.commit()

    return ok({
        "access_token": token,
        "refresh_token": token,
        "user": _user_out(user),
    })


@router.post("/logout", dependencies=[rate_limit(times=30)])
def logout(body: LogoutIn, db: Session = Depends(get_db)) -> dict:
    """Гасимо сесію (якщо жива). Повторний виклик — не помилка."""
    revoke_session(db, body.refresh_token)
    return ok({"logged_out": True})


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return ok(_user_out(user))


def _session_out(s: RefreshSession, current_hash: str) -> dict:
    """Публічний вигляд сесії. id — окремий публічний ідентифікатор
    (НЕ токен і не його хеш): за ним можна лише відкликати сесію."""
    return {
        "id": s.public_id,
        "current": bool(current_hash) and s.id == current_hash,
        "user_agent": s.user_agent or "",
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
    }


@router.get("/sessions")
def list_sessions(current: str = "",
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> dict:
    """`current` — токен поточної сесії клієнта (для позначки current)."""
    now = naive_utcnow()
    rows = (db.query(RefreshSession)
            .filter(RefreshSession.user_id == user.id,
                    RefreshSession.revoked_at.is_(None),
                    RefreshSession.expires_at >= now)
            .order_by(RefreshSession.created_at.desc())
            .all())
    cur = hash_token(current) if current.strip() else ""
    return ok([_session_out(r, cur) for r in rows])


@router.post("/sessions/revoke", dependencies=[rate_limit(times=30)])
def revoke_session_route(body: SessionRevokeIn,
                         user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)) -> dict:
    s = (db.query(RefreshSession)
         .filter(RefreshSession.public_id == body.session_id.strip(),
                 RefreshSession.user_id == user.id)
         .first())
    if s is None:
        raise ApiError(404, "session_not_found", "session_id",
                       "session_not_found")
    revoked = False
    if s.revoked_at is None:
        s.revoked_at = naive_utcnow()
        db.commit()
        revoked = True
    return ok({"revoked": revoked})


@router.post("/sessions/revoke-others", dependencies=[rate_limit(times=10)])
def revoke_other_sessions(body: SessionsRevokeOthersIn,
                          user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)) -> dict:
    keep = hash_token(body.keep)  # keep = токен поточної сесії
    rows = (db.query(RefreshSession)
            .filter(RefreshSession.user_id == user.id,
                    RefreshSession.revoked_at.is_(None),
                    RefreshSession.id != keep)
            .all())
    n = 0
    for s in rows:
        s.revoked_at = naive_utcnow()
        n += 1
    if n:
        db.commit()
    return ok({"revoked": n})