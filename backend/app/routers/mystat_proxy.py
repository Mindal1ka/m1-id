"""Універсальний spec-driven проксі /api/mystat/* — серце шлюзу.

Клієнт викликає:  ANY /api/mystat/v1/mystat/{branch}/...?...
Бекенд:
  1. звіряє шлях+метод зі SpecRegistry (немає в специ → 404 unknown_endpoint);
  2. підставляє {branch_alias} гілки акаунта;
  3. додає Bearer-токен акаунта + X-Language + X-UserId;
  4. при 401 робить refresh-ланцюжок і повторює запит;
  5. загортає відповідь у конверт {ok, data, meta, error}
     (X-Pagination-* → meta.pagination).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.responses import ApiError, envelope
from app.core.security import decrypt_secret
from app.db.models import MystatAccount, User
from app.deps import get_current_user, get_db
from app.services import mystat_client as ms
from app.services.ratelimit import rate_limit_user
from sqlalchemy.orm import Session

_log = logging.getLogger("m1id")

router = APIRouter(prefix="/api/mystat", tags=["MyStat Proxy"])

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]

_PAGINATION_KEYS = {
    # канонічні Laravel-заголовки (MYSTAT_API §13: X-Pagination-Page-count)
    "x-pagination-current-page": "current_page",
    "x-pagination-page-count": "page_count",
    "x-pagination-total-pages": "total_pages",   # альтернативна назва, про всяк випадок
    "x-pagination-total-count": "total_count",
    "x-pagination-per-page": "per_page",
}


def _get_account(db: Session, user: User, account_id: int | None) -> MystatAccount:
    if account_id is not None:
        # __account — публічний номер акаунта користувача (user_seq)
        account = (db.query(MystatAccount)
                   .filter(MystatAccount.user_id == user.id,
                           MystatAccount.user_seq == account_id)
                   .first())
    else:
        account = (db.query(MystatAccount)
                   .filter(MystatAccount.user_id == user.id,
                           MystatAccount.status == "active")
                   .order_by(MystatAccount.id)
                   .first())
        if account is None:
            # немає активних — беремо перший (needs_relogin тощо): клієнт
            # отримає чесний 401/502, а не хибне «акаунта немає»
            account = (db.query(MystatAccount)
                       .filter(MystatAccount.user_id == user.id)
                       .order_by(MystatAccount.id)
                       .first())
    if account is None or account.user_id != user.id:
        raise ApiError(404, "account_not_found", "__all__",
                       "link_mystat_account_first")
    return account


MAX_BODY_BYTES = 64 * 1024 * 1024

# Чутливі маршрути MyStat, які НЕ можна проходити через універсальний проксі:
# автентифікація/сесії, зміна пароля й особистих даних, відправка листів,
# видалення ДЗ тощо. Ці операції - лише через наші окремі ендпоїнти
# (з rate-limit і додатковими перевірками). Шлях порівнюється без префікса
# гілки {branch_alias}, у нижньому регістрі.
_DENY_RE = re.compile(
    r"^/v1/mystat/(?:[^/]+/)?"
    r"(?:auth(?:/|$)"                       # login/logout/refresh/me/password/*
    r"|user-storage/password"               # пароль сховища
    r"|sms/"                                # підтвердження телефону
    r"|relatives/get-phones-to-auth"
    r"|contacts/send-"                      # листи директору/викладачу
    r"|homework/delete(?:/|$)"              # видалення здачі ДЗ
    r"|survey-user-attempts/"               # видалення спроб опитувань
    r"|custom-awards/award/"
    r"|admin/"                              # адмінські дії (login-student тощо)
    r"|user/file-token"                     # токен файлового сервера
    r"|signal(?:/|$))",
    re.IGNORECASE)
# Допоміжно: будь-який шлях з цими сегментами вважаємо чутливим
_DENY_SEGMENTS = {"login", "logout", "refresh", "login-by-auth-code"}


def _is_denied(path: str, method: str) -> bool:
    p = "/" + path.strip("/").lower()
    # /signal: GET problems-list дозволений (довідник), POST - ні
    if p.endswith("/signal/problems-list"):
        return False
    if _DENY_RE.match(p):
        return True
    return any(seg in _DENY_SEGMENTS for seg in p.split("/"))


async def _read_body_limited(request: Request, limit: int = MAX_BODY_BYTES) -> bytes:
    """N-M1: читаємо тіло потоково з жорстким лімітом.

    Перевірка лише Content-Length обходиться через
    Transfer-Encoding: chunked (CL відсутній → await request.body()
    читає необмежено). Тут акумулюємо чанки і при перевищенні ліміта
    кидаємо 413 ДО повного читання тіла в пам'ять."""
    stream = request.stream()
    chunks: list[bytes] = []
    total = 0
    async for chunk in stream:
        total += len(chunk)
        if total > limit:
            raise ApiError(413, "body_too_large", "__all__",
                           "request_body_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def _pagination_meta(resp) -> dict | None:
    meta: dict[str, Any] = {}
    for header, key in _PAGINATION_KEYS.items():
        value = resp.headers.get(header)
        if value is not None:
            try:
                meta[key] = int(value)
            except ValueError:
                meta[key] = value
    return {"pagination": meta} if meta else None


@router.api_route("/{path:path}", methods=METHODS,
                  dependencies=[rate_limit_user(times=240)])
async def proxy(path: str, request: Request,
                __account: int | None = Query(default=None, alias="__account"),
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    mapi_path = "/" + path.lstrip("/")
    method = request.method.upper()

    # 0. денілист чутливих маршрутів (до звірки зі специфікацією)
    if _is_denied(mapi_path, method):
        raise ApiError(403, "forbidden_endpoint", "__all__",
                       "Цей маршрут недоступний через проксі. "
                       "Використовуйте відповідну функцію застосунку.")

    # 1. spec-driven перевірка маршруту
    hit = request.app.state.registry.match(method, mapi_path)
    if hit is None:
        raise ApiError(404, "unknown_endpoint", "__all__",
                       f"no {method} {mapi_path} in openapi.json")
    op, path_params = hit

    account = _get_account(db, user, __account)
    if account.status == "needs_relogin":
        raise ApiError(401, "account_needs_relogin", "__all__",
                       "re_enter_mystat_credentials")

    # 2. підміна branch_alias значенням із профілю токена
    if "branch_alias" in path_params and account.branch_alias:
        path_params["branch_alias"] = account.branch_alias
    concrete_path = op.concrete_path(**path_params)

    query: dict[str, Any] = {}
    # getlist: multi-value параметри (type[]=1&type[]=2) НЕ мусять
    # схлопуватися до останнього значення — items() губив усе, крім одного
    for key in request.query_params.keys():
        if key == "__account":
            continue
        values = request.query_params.getlist(key)
        query[key] = values[0] if len(values) == 1 else values
    body: Any = None
    raw_body: tuple[bytes, str] | None = None
    if method in ("POST", "PUT", "PATCH"):
        # Запобіжник пам'яті: проксі читає тіло ЦІЛКОМ (multipart —
        # як є). Без ліміту авторизований клієнт міг би впалити
        # процес одним POST на гігабайти. 64 МіБ покриває будь-який
        # легітимний JSON; файлова здача ДЗ іде через /api/app/homework
        # (там свій пер-файловий ліміт 25 МБ).
        cl = request.headers.get("content-length")
        if cl and (cl.isascii() and cl.isdigit()) and int(cl) > MAX_BODY_BYTES:
            # N-M1: early-fast-path (CL-перевірка лишається, але не є
            # єдиним захистом — див. _read_body_limited)
            raise ApiError(413, "body_too_large", "__all__",
                           "request_body_too_large")
        raw = await _read_body_limited(request)
        ctype = request.headers.get("content-type", "")
        if raw:
            if ctype.startswith("multipart/form-data"):
                # multipart (фото/файли) — прозорий passthrough
                raw_body = (raw, ctype)
            else:
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    body = raw.decode("utf-8", errors="replace")

    language = account.language or "uk"
    try:
        token = decrypt_secret(account.access_token_enc)
    except ValueError:
        account.status = "needs_relogin"
        db.commit()
        raise ApiError(401, "account_needs_relogin", "__all__",
                       "token_unreadable_after_restart_re_link_account")

    # 2½. проактивний refresh: тот, що спливає/сплив, токен оновлюємо ДО
    # запиту (економить 401-раундтрип; refresh_once дедуплікує гонки).
    # best-effort: мережевий збій при проактивному refresh не мусить валити
    # запит — продовжуємо зі старим токеном (401-ланцюжок нижче підстрахує)
    exp = account.token_expires_at
    if exp is not None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if exp <= now + timedelta(seconds=120):
            try:
                new_token = await ms.refresh_once(
                    token, language, user_id=account.id_user_storage or None)
                if new_token:
                    ms.set_account_token(account, new_token)
                    db.commit()
                    token = new_token
            except Exception:
                _log.warning("mapi_call_fail proactive_refresh %s id=%s",
                             "refresh", account.id)

    # 3–4. виклик із ланцюжком 401 → refresh → повтор (до 3 запитів).
    # B9 fix: після успішного refresh повторюємо запит ЗАВЖДИ (у т.ч. на
    # 2-й спробі) — раніше цикл завершувався і клієнт отримував 401, хоча
    # токен щойно оновлено. Мережеві збої (таймаут/обрив/DNS/SSL) → 502.
    resp = None
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            resp = await ms.request_async(
                method, concrete_path, token=token, language=language,
                user_id=account.id_user_storage or None,
                params=query or None, json_body=body, raw=raw_body,
            )
        except Exception as e:
            _log.warning("mapi_call_fail %s %s attempt=%s err=%s",
                         method, concrete_path, attempt,
                         type(e).__name__)
            if attempt == max_attempts or method not in ("GET", "HEAD"):
                # повтор неідемпотентного POST/PUT після таймаута міг би
                # задвоїти операцію апстрима (таймаут ≠ «не виконано»)
                raise ApiError(502, "upstream_unreachable", "__all__",
                               "mystat_api_temporarily_unreachable")
            continue
        if resp.status_code != 401:
            break
        if attempt == max_attempts:
            # токен щойно оновлено, але повторів більше не лишилось:
            # віддаємо останню відповідь як є (не крутитись вічно)
            break
        try:
            new_token = await ms.refresh_once(
                token, language, user_id=account.id_user_storage or None)
        except ms.MystatError as exc:
            # транзієнтна аварія апстрима при refresh — НЕ «сесія померла»:
            # чесний 502, статус акаунта не чіпаємо (не 500 і не релогін)
            _log.warning("mapi_refresh_transient %s %s: %s",
                         method, concrete_path, exc)
            raise ApiError(502, "upstream_unreachable", "__all__",
                           "mystat_temporarily_unreachable_during_refresh") from exc
        if new_token is None:
            account.status = "needs_relogin"
            db.commit()
            raise ApiError(401, "account_needs_relogin", "__all__",
                           "refresh_failed_re_enter_credentials")
        token = new_token
        ms.set_account_token(account, new_token)
        db.commit()
        # B9: гарантуємо повторний запит зі свіжим токеном на наступній
        # ітерації циклу (for продовжиться, бо max_attempts не вичерпано)

    assert resp is not None

    # 5. конверт
    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data: Any = resp.json()
        except json.JSONDecodeError:
            data = resp.text
    else:
        data = resp.text

    if resp.status_code >= 400:
        if isinstance(data, list):  # рідний формат помилок mapi [{field,message}]
            errors = data
        elif isinstance(data, dict):
            message = str(data.get("error") or data.get("message") or data)
            errors = [{"field": "__all__", "message": message[:300]}]
        else:
            errors = [{"field": "__all__", "message": str(data)[:300]}]
        return JSONResponse(status_code=resp.status_code,
                            content=envelope(False, error=errors))

    return JSONResponse(status_code=200, content=envelope(
        True, data=data, meta=_pagination_meta(resp)))
