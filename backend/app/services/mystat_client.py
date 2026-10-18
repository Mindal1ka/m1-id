"""Клієнт живого API MyStat (mapi.itstep.org) — за MYSTAT_API.md §1–§3.

Заголовки: Authorization: Bearer <JWT>, X-Language, X-UserId.
Помилки у форматі [{field,message}] або {"error": ...} — приводимо до рядка.
Для тестів можна підмінити транспорт (httpx.MockTransport).
"""
from __future__ import annotations

import asyncio
import contextlib
import threading
import time
import weakref
from datetime import datetime, timezone
from collections.abc import Iterator
from typing import Any

import httpx
import jwt

from app.core.config import get_settings


class MystatError(Exception):
    """Помилка виклику живого API MyStat."""

    def __init__(self, status_code: int, message: str, payload: Any = None):
        self.status_code = status_code
        self.message = message
        self.payload = payload
        super().__init__(f"[{status_code}] {message}")


# --- транспорт (перевизначається в тестах через MockTransport) ---

_sync_transport: httpx.BaseTransport | None = None
_async_transport: httpx.AsyncBaseTransport | None = None

# Спільний AsyncClient із connection-pool: один TLS-handshake на багато запитів
# до mapi замість нового клієнта (і handshake) на кожен виклик.
_shared_async_client: httpx.AsyncClient | None = None


def set_transport(
    sync: httpx.BaseTransport | None = None,
    async_: httpx.AsyncBaseTransport | None = None,
) -> None:
    global _sync_transport, _async_transport, _shared_async_client
    _sync_transport = sync
    _async_transport = async_
    _shared_async_client = None  # тести підмінюють транспорт до старту app


def open_async_client() -> httpx.AsyncClient:
    """ОДНОРАЗОВИЙ клієнт (закриває той, хто викликає, через async with).
    Для фонових потоків зі своїм event loop (sync_engine thread-fallback).
    У звичайних запитах використовуй shared_async_client()."""
    return httpx.AsyncClient(
        transport=_async_transport,
        timeout=get_settings().sync_timeout_seconds,
    )


def shared_async_client() -> httpx.AsyncClient:
    """Живе весь час процесу (закривається в lifespan shutdown).
    keepalive-пул: повторні виклики mapi не платять за TLS-handshake."""
    global _shared_async_client
    if _shared_async_client is None or _shared_async_client.is_closed:
        _shared_async_client = httpx.AsyncClient(
            transport=_async_transport,
            timeout=get_settings().sync_timeout_seconds,
            limits=httpx.Limits(max_connections=100,
                                max_keepalive_connections=20),
        )
    return _shared_async_client


async def close_async_client() -> None:
    """Graceful shutdown: закрити спільний пул з'єднань."""
    global _shared_async_client
    if _shared_async_client is not None and not _shared_async_client.is_closed:
        await _shared_async_client.aclose()
    _shared_async_client = None


def _base_url() -> str:
    return get_settings().mystat_api_base.rstrip("/")


def _headers(token: str | None = None, language: str = "uk",
             user_id: str | int | None = None) -> dict[str, str]:
    """Профіль заголовків оригінального фронта (MYSTAT_API §2):
    Authorization + X-Language завжди; X-UserId — завжди після логіна.
    Origin/Referer/User-Agent серверу не потрібні (перевірено probe_verify)."""
    headers: dict[str, str] = {
        "Accept": "application/json",
        "X-Language": language,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if user_id:
        headers["X-UserId"] = str(user_id)
    return headers


def extract_error(resp: httpx.Response) -> str:
    """Людське повідомлення з будь-якого формату помилок mapi."""
    try:
        data = resp.json()
    except Exception:
        return resp.text[:200] or f"http_{resp.status_code}"
    if isinstance(data, list):  # формат [{field,message}]
        parts = [str(i.get("message", i)) for i in data if isinstance(i, dict)]
        return "; ".join(parts) if parts else str(data)[:200]
    if isinstance(data, dict):
        for key in ("error", "message", "status"):
            if key in data and data[key] not in ("error", None):
                return str(data[key])[:200]
    return str(data)[:200]


# ------------------------------------------------------------------ auth


def login(login_value: str, password: str) -> dict[str, Any]:
    """POST /mystat/auth/login → access_token (JWT на 30 днів).

    Відповідь буває JSON {access_token} АБО text/plain JWT — приймаємо обидва."""
    with httpx.Client(transport=_sync_transport, timeout=15.0) as client:
        resp = client.post(
            f"{_base_url()}/v1/mystat/auth/login",
            json={"login": login_value, "password": password},
            headers=_headers(),
        )
    if resp.status_code != 200:
        raise MystatError(resp.status_code, extract_error(resp))
    token = _extract_token(resp)
    if not token:
        raise MystatError(502, "login_response_without_token", resp.text[:200])
    return {"access_token": token, "raw": resp.text[:4000]}


async def login_async(login_value: str, password: str) -> dict[str, Any]:
    """Асинхронний логін: НЕ блокує event loop (див. login — sync-версія
    лишилася для скриптів/тестів). Відповідь JSON {access_token} АБО text/plain."""
    client = shared_async_client()
    try:
        resp = await client.post(
            f"{_base_url()}/v1/mystat/auth/login",
            json={"login": login_value, "password": password},
            headers=_headers(),
        )
    except httpx.HTTPError as exc:
        # мережева аварія апстрима → чесний 502, а не 500
        raise MystatError(502, f"mystat_unreachable_{type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise MystatError(resp.status_code, extract_error(resp))
    token = _extract_token(resp)
    if not token:
        raise MystatError(502, "login_response_without_token", resp.text[:200])
    return {"access_token": token, "raw": resp.text[:4000]}


def token_exp(token: str) -> datetime | None:
    """exp із JWT MyStat (без перевірки підпису — токен отримано по TLS від
    mapi, читаємо лише claim exp для token_expires_at). None — не JWT."""
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        exp = payload.get("exp")
        if exp:
            return datetime.fromtimestamp(int(exp), tz=timezone.utc)\
                .replace(tzinfo=None)
    except Exception:
        pass
    return None


def set_account_token(account, plain_token: str) -> None:
    """Єдина точка збереження токена MyStat: шифруємо + фіксуємо exp
    (раніше token_expires_at ніколи не заповнювався)."""
    from app.core.security import encrypt_secret

    account.access_token_enc = encrypt_secret(plain_token)
    account.token_expires_at = token_exp(plain_token)


def _extract_token(resp: httpx.Response) -> str | None:
    """access_token із JSON або «голий» JWT із text/plain (MYSTAT_API §3)."""
    try:
        data = resp.json()
        if isinstance(data, dict):
            token = data.get("access_token") or data.get("token")
            if token:
                return str(token)
    except Exception:
        pass
    text = resp.text.strip().strip('"')
    if text.count(".") == 2 and len(text) > 40:  # схоже на JWT
        return text
    return None


def refresh_token(old_token: str, language: str = "uk",
                  user_id: str | int | None = None) -> str | None:
    """POST /mystat/auth/refresh — «ревок» токена при 401. None → не спасти.

    Відповідь: JSON {access_token} або text/plain JWT."""
    with httpx.Client(transport=_sync_transport, timeout=15.0) as client:
        resp = client.post(
            f"{_base_url()}/v1/mystat/auth/refresh",
            json={},
            headers=_headers(old_token, language, user_id),
        )
    if resp.status_code != 200:
        return None
    return _extract_token(resp)


async def refresh_token_async(old_token: str, language: str = "uk",
                              user_id: str | int | None = None) -> str | None:
    """Асинхронний варіант refresh — для рушія і проксі (не блокує loop).

    → None ЛИШЕ коли mapi однозначно відхилив сесію (400/401/403):
    лише в цьому випадку акаунт позначається needs_relogin. Транзієнтні
    збої (5xx/429/таймаут/DNS) → MystatError: сесія ще жива, це
    аварія апстрима, а не привід викидати користувача на релогін."""
    try:
        async with httpx.AsyncClient(transport=_async_transport,
                                     timeout=15.0) as client:
            resp = await client.post(
                f"{_base_url()}/v1/mystat/auth/refresh",
                json={},
                headers=_headers(old_token, language, user_id),
            )
    except httpx.HTTPError as exc:
        raise MystatError(503, f"refresh_unreachable_{type(exc).__name__}") from exc
    if resp.status_code in (400, 401, 403):
        return None
    if resp.status_code != 200:
        raise MystatError(resp.status_code, extract_error(resp))
    return _extract_token(resp)


# Єдина точка 401-refresh (single-flight). MyStat «ревокає» старий JWT при
# першому ж /auth/refresh, тож паралельні запити з одним і тим самим
# простроченим токеном не мають оновлювати його одночасно: інакше всі,
# крім першого, отримають None → хибний needs_relogin в акаунта.
# Ключ — САМ LOOP-об'єкт (WeakKeyDictionary): ключ id(loop) перевикористовується
# після GC, і новий loop отримав би мертвий Lock чужого loop'а →
# RuntimeError «bound to a different event loop» всередині refresh_once.
# Лок на КОЖЕН old_token (а не один глобальний на loop): refresh різних
# акаунтів не серіалізуються. Структура: loop → {token: [lock, refcount]};
# запис видаляється, коли на токен більше немає очікувачів.
_refresh_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, list]]" =     weakref.WeakKeyDictionary()
_refresh_locks_guard = threading.Lock()
# old_token → (monotonic_ts, new_token). Ключ — сам токен: один глобальний
# слот витіснявся паралельними синками ІНШИХ акаунтів, і повторний 401
# того самого акаунта ішов у mapi з уже відкликаним токеном → хибний
# needs_relogin. Невдалі refresh кешуються на 30с — не турбуємо mapi.
_recent_refresh: dict[str, tuple[float, str]] = {}
# (B4) словник обмежений: при переповненні витісняється найстаріший запис,
# а не clear() усього кешу (пер-акаунтні записи не губляться)
_recent_refresh_guard = threading.Lock()
_REFRESH_TTL = 120.0
_REFRESH_NEG_TTL = 30.0


@contextlib.asynccontextmanager
async def _refresh_lock_for_token(old_token: str):
    """asyncio.Lock прив'язаний до event loop, тому тримаємо locks по loop'у
    (ключ — сам loop, слабке посилання) і всередині — по одному локу на
    old_token. Лічильник посилань дозволяє прибрати лок після використання."""
    loop = asyncio.get_running_loop()
    with _refresh_locks_guard:
        per_loop = _refresh_locks.setdefault(loop, {})
        entry = per_loop.get(old_token)
        if entry is None:
            entry = per_loop[old_token] = [asyncio.Lock(), 0]
        entry[1] += 1
    try:
        async with entry[0]:
            yield
    finally:
        with _refresh_locks_guard:
            entry[1] -= 1
            if entry[1] <= 0 and per_loop.get(old_token) is entry:
                del per_loop[old_token]


async def refresh_once(old_token: str, language: str = "uk",
                       user_id: str | int | None = None) -> str | None:
    """refresh_token_async із захистом від гонок: якщо цей самий old_token уже
    оновила інша корутина — повернути готовий новий токен без повторного
    запиту (повтор по відкликаному токену означав би втрату сесії).

    MystatError (транзієнтна аварія апстрима) НЕ кешується і пробрасується:
    наступний запит може пройти — вважати сесію мертвою рано."""
    async with _refresh_lock_for_token(old_token):
        now = time.monotonic()
        with _recent_refresh_guard:
            hit = _recent_refresh.get(old_token)
        if hit is not None:
            ts, cached = hit
            ttl = _REFRESH_TTL if cached else _REFRESH_NEG_TTL
            if now - ts < ttl:
                return cached or None
        with _recent_refresh_guard:
            # B4 fix: НЕ clear() усього дедуп-кешу (він спільний для всіх
            # акаунтів — clear скидав кеш ЧУЖИХ акаунтів → хибні повторні
            # refresh / needs_relogin). Витісняємо найстаріші записи.
            while len(_recent_refresh) >= 256:
                _recent_refresh.pop(min(_recent_refresh,
                                        key=lambda k: _recent_refresh[k][0]))
        new_token = await refresh_token_async(old_token, language,
                                              user_id=user_id)
        with _recent_refresh_guard:
            _recent_refresh[old_token] = (now, new_token or "")
        return new_token


async def request_async(method: str, path: str, *, token: str,
                        language: str = "uk", user_id: str | int | None = None,
                        params: dict | None = None,
                        json_body: Any = None,
                        raw: tuple[bytes, str] | None = None) -> httpx.Response:
    """Універсальний виклик гілкового/безгілкового ендпоінта.

    raw=(bytes, content_type) — пряма передача тіла (multipart проксі)."""
    headers = _headers(token, language, user_id)
    kwargs: dict[str, Any] = {"params": params}
    if raw is not None:
        body_bytes, ctype = raw
        kwargs["content"] = body_bytes
        headers = {**headers, "Content-Type": ctype}
    else:
        kwargs["json"] = json_body

    client = shared_async_client()
    return await client.request(
        method.upper(),
        f"{_base_url()}{path}",
        headers=headers,
        **kwargs,
    )


# ------------------------------------------------------------------ профіль


async def auth_me_async(token: str, language: str = "uk") -> dict[str, Any]:
    try:
        resp = await request_async("POST", "/v1/mystat/auth/me",
                                   token=token, language=language)
    except httpx.HTTPError as exc:
        raise MystatError(502, f"mystat_unreachable_{type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise MystatError(resp.status_code, extract_error(resp))
    return resp.json()


def auth_me(token: str, language: str = "uk") -> dict[str, Any]:
    """Синхронна обгортка для контекстів без працюючого loop."""
    import asyncio

    try:
        asyncio.get_running_loop()
        raise RuntimeError("use await auth_me_async() inside event loop")
    except RuntimeError as exc:
        if "use await" in str(exc):
            raise
    return asyncio.run(auth_me_async(token, language))


def parse_me(me: dict[str, Any]) -> dict[str, str]:
    """Нормалізація /auth/me за РЕАЛЬНОЮ живою структурою (diag_me.py, 2026-08-24):
    {id, id_user_storage, name, lang, branch_alias, user_profiles{proj:{br:[...]}}}.
    Два різні ID не плутати: id=logbook_id ≠ id_user_storage=X-UserId."""
    branch = me.get("branch")
    branch = branch if isinstance(branch, dict) else {}

    # FIO: плоске name → user_storage(прізвище ім'я по батькові) → username
    fio = str(me.get("name") or "").strip()
    if not fio:
        storage = me.get("user_storage")
        storage = storage if isinstance(storage, dict) else {}
        parts = [storage.get("lastname"), storage.get("firstname"),
                 storage.get("patronymic")]
        fio = " ".join(p for p in parts if p)
    if not fio:
        fio = str(me.get("username") or "Мій акаунт")

    def _iter_profiles() -> Iterator[dict]:
        """user_profiles{project_id:{branch_id:[profile,…]}} з гардами:
        mapi може повернути не-dict на будь-якому рівні — не роняємо парсинг."""
        profiles_map = me.get("user_profiles")
        if not isinstance(profiles_map, dict):
            return
        for by_branch in profiles_map.values():
            if not isinstance(by_branch, dict):
                continue
            for profiles in by_branch.values():
                if isinstance(profiles, list) and profiles:
                    for p in profiles:
                        if isinstance(p, dict):
                            yield p

    profiles = list(_iter_profiles())

    # фото: перший профіль із фото
    photo = ""
    for p in profiles:
        photo = str(p.get("photo") or "")
        if photo:
            break

    # логін MyStat: верхньорівневий login → user_profiles[0].login → username
    login = str(me.get("login") or "")
    if not login:
        for p in profiles:
            login = str(p.get("login") or "")
            if login:
                break
    if not login:
        login = str(me.get("username") or "")

    # для батька тут згодом візьмемо childs[*].profiles[*] (multi-child, M2+)
    return {
        "login": login[:64],
        "branch_alias": str(me.get("branch_alias") or branch.get("alias") or ""),
        "logbook_id": str(me.get("logbook_id") or me.get("id") or ""),
        "id_user_storage": str(
            me.get("id_user_storage") or me.get("user_storage_id") or ""
        ),
        "fio": fio[:255],
        "photo_url": photo,
        "language": str(me.get("lang") or me.get("language")
                        or get_settings().default_language),
    }
