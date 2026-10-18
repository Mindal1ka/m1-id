"""Криптоядро M1 ID: паролі (Argon2id), сесії (хеш токена в БД), ключ HMAC,
шифрування токенів MyStat (Fernet)."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import threading
from datetime import timedelta
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

_log = logging.getLogger("m1id.security")

_ph = PasswordHasher()

# ------------------------------------------------------------------ паролі


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# Фіктивний хеш: коли користувача не знайдено, все одно виконуємо Argon2-
# перевірку, щоб час відповіді не видавав існування логіна (timing-атака).
_DUMMY_HASH: str | None = None
_dummy_lock = threading.Lock()


def dummy_verify(password: str) -> None:
    """Витрачає той самий час, що й перевірка реального пароля."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        with _dummy_lock:
            if _DUMMY_HASH is None:
                _DUMMY_HASH = _ph.hash(secrets.token_urlsafe(16))
    verify_password(_DUMMY_HASH, password)


# ------------------------------------------------------------------ ключ-файли


def _write_key_bytes(path: Path, data: bytes) -> None:
    """Атомарний запис ключа: tmp + replace, права 0600 (де ОС підтримує).
    Частковий запис через падіння процесу = невалідний ключ = втрата
    всіх токенів, тому пишемо через тимчасовий файл."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    try:
        os.chmod(tmp, 0o600)  # на Windows майже no-op, на POSIX — гарантія
    except OSError:
        pass
    tmp.replace(path)


def _write_key_text(path: Path, data: str) -> None:
    _write_key_bytes(path, data.encode("utf-8"))


# ------------------------------------------------------------------ ключ HMAC

# Файл-ключ: якщо M1ID_SECRET_KEY не задано — ключ генерується ОДИН раз
# і переживає рестарти. Дефолт «dev-insecure-change-me» не використовується:
# відомий ключ = підробка підписів (напр. токенів прив'язки Telegram).
_JWT_KEY_FILE = Path(__file__).resolve().parents[2] / ".jwt_key"
_jwt_key_cache: str | None = None
_key_write_lock = threading.Lock()


def jwt_secret() -> str:
    """Пріоритет: M1ID_SECRET_KEY (≠ дев-дефолт) → файл .jwt_key → ephemeral.

    Кеш у пам'яті + замок + атомарний запис: два потоки на холодному
    старті не створять різні ключі."""
    global _jwt_key_cache
    if _jwt_key_cache is not None:
        return _jwt_key_cache
    configured = (get_settings().secret_key or "").strip()
    if configured and configured != "dev-insecure-change-me":
        if len(configured) < 32:
            _log.warning("M1ID_SECRET_KEY коротший за 32 байти — "
                         "рекомендується довший (secrets.token_urlsafe(48))")
        _jwt_key_cache = configured
        return configured
    with _key_write_lock:
        if _jwt_key_cache is not None:
            return _jwt_key_cache
        try:
            raw = _JWT_KEY_FILE.read_text(encoding="utf-8").strip()
            if raw:
                _jwt_key_cache = raw
                return raw
        except FileNotFoundError:
            pass
        raw = secrets.token_urlsafe(48)
        try:
            _write_key_text(_JWT_KEY_FILE, raw)
            _log.info("створено файл-ключ %s; задай M1ID_SECRET_KEY в env, "
                      "щоб контролювати ключ на проді", _JWT_KEY_FILE.name)
        except OSError:
            _log.warning("не вдалося записати .jwt_key — ключ ефемерний "
                         "(один на процес), підписи зникнуть при рестарті")
        _jwt_key_cache = raw
    return _jwt_key_cache


# ------------------------------------------------------------------ сесії M1 ID
# Один довгоживучий сесійний токен. У БД зберігається ЛИШЕ sha256-хеш
# токена (sessions.id): витік БД/бекапу не дає готових токенів. Для UI є
# окремий публічний id (sessions.public_id), що з токеном не пов'язаний.

from app.db.models import RefreshSession, User  # noqa: E402


def hash_token(token: str) -> str:
    """sha256(token) у hex — ключ рядка сесії в БД."""
    return hashlib.sha256((token or "").strip().encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_hex(16)  # 32 hex-символи (128 біт ентропії)


def create_session(db, user_id: int, user_agent: str) -> str:
    """Нова сесія: 30 днів (settings.refresh_token_expire_days).
    Повертає ТОКЕН (відкритий вигляд існує лише в цій відповіді)."""
    from app.core.clock import naive_utcnow
    token = new_session_token()
    now = naive_utcnow()
    db.add(RefreshSession(
        id=hash_token(token),
        public_id=secrets.token_hex(16),
        user_id=user_id,
        expires_at=now + timedelta(days=get_settings().refresh_token_expire_days),
        user_agent=(user_agent or "")[:255],
        last_seen_at=now,
    ))
    db.commit()
    return token


def find_session(db, token: str) -> RefreshSession | None:
    """Жива (не відкликана, не прострочена) сесія за токеном або None."""
    from app.core.clock import naive_utcnow
    token = (token or "").strip()
    if not token:
        return None
    s = db.get(RefreshSession, hash_token(token))
    if s is None or s.revoked_at is not None:
        return None
    if s.expires_at is not None and s.expires_at < naive_utcnow():
        return None
    return s


def touch_session(db, s: RefreshSession) -> None:
    """Sliding-продовження: якщо до кінця строку лишилось <7 днів —
    продовжуємо на повний TTL. Запис у БД лише в цьому рідкому випадку
    (а не на кожен GET)."""
    from app.core.clock import naive_utcnow
    now = naive_utcnow()
    if s.expires_at is not None and (s.expires_at - now) < timedelta(days=7):
        s.expires_at = now + timedelta(
            days=get_settings().refresh_token_expire_days)
        s.last_seen_at = now
        db.commit()


def session_user_from_token(db, token: str) -> User | None:
    """Користувач за сесійним токеном або None."""
    s = find_session(db, token)
    if s is None:
        return None
    touch_session(db, s)
    return db.get(User, s.user_id)


def revoke_session(db, token: str) -> bool:
    from app.core.clock import naive_utcnow
    s = db.get(RefreshSession, hash_token(token))
    if s is not None and s.revoked_at is None:
        s.revoked_at = naive_utcnow()
        db.commit()
        return True
    return False


def purge_stale_sessions(db, revoked_keep_days: int = 7) -> int:
    """Видаляє прострочені сесії та відкликані понад N днів тому."""
    from app.core.clock import naive_utcnow
    now = naive_utcnow()
    n = (db.query(RefreshSession)
         .filter((RefreshSession.expires_at < now)
                 | (RefreshSession.revoked_at < now - timedelta(
                     days=revoked_keep_days)))
         .delete(synchronize_session=False))
    db.commit()
    return n


# ------------------------------------------------------------------ шифрування токенів MyStat
# Ключ із env; якщо задано довільним рядком — деривуємо валідний Fernet-ключ.

_fernet_cache: Fernet | None = None

# файл-ключ: якщо M1ID_TOKEN_ENC_KEY не задано, ключ живе тут і
# ПЕРЕЖИВАЄ рестарти (інакше токени в БД щоразу «губились»)
_KEY_FILE = Path(__file__).resolve().parents[2] / ".token_key"


def _derive(raw: bytes) -> bytes:
    """Валідний Fernet-ключ: як є, або sha256 → urlsafe-base64."""
    try:
        Fernet(raw)
        return raw
    except Exception:
        return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())


def _fernet() -> Fernet:
    """Fernet з кешем: ключ деривується/читається з диска один раз.
    Пріоритет: env-ключ → файл-ключ → ephemeral (останній ресурс).
    Генерація/запис файлу — під замком і атомарно."""
    global _fernet_cache
    if _fernet_cache is not None:
        return _fernet_cache

    with _key_write_lock:
        if _fernet_cache is not None:
            return _fernet_cache

        configured = (get_settings().token_enc_key or "").strip()
        if configured:
            _fernet_cache = Fernet(_derive(configured.encode()))
            return _fernet_cache

        try:
            raw = _KEY_FILE.read_bytes().strip()
            if raw:
                _fernet_cache = Fernet(_derive(raw))
                return _fernet_cache
        except FileNotFoundError:
            pass

        key = Fernet.generate_key()
        try:
            _write_key_bytes(_KEY_FILE, key)
            _log.info("створено файл-ключ %s — токени переживуть рестарти",
                      _KEY_FILE.name)
        except OSError:
            _log.warning("не вдалося записати файл-ключ — токени НЕ "
                         "переживуть рестарт процесу")
        _fernet_cache = Fernet(key)
        return _fernet_cache


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token_enc: str) -> str:
    try:
        return _fernet().decrypt(token_enc.encode()).decode()
    except InvalidToken as exc:  # ключ змінився — токен не відновити
        raise ValueError("cannot_decrypt_stored_token") from exc
