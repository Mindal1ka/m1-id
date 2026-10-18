"""Перегляд файлів ДЗ у браузері без завантаження.

Фронтенд просить бекенд «проксуй мені файл з fs*.itstep.org» — і
рендерить його локально (PDF в iframe, зображення, txt, DOCX через
docx-preview, ZIP-архіви через JSZip). Бекенд лише безпечно передає
байти: стрімінг з жорстким лімітом розміру, allowlist хостів
(SSRF-запобіжник), Content-Disposition: inline.

Посилання на файли приходять з апстрима у вигляді
https://fs3.itstep.org/api/v1/files/<token> — публічні, токен
акаунта не потрібен. Спільний httpx-клієнт (shared_async_client)
приймає абсолютні URL — пул з'єднань пере­використовується.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import AsyncIterator
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.responses import ApiError
from app.db.models import User
from app.deps import get_current_user
from app.services import mystat_client as ms
from app.services.ratelimit import rate_limit_user

_log = logging.getLogger("m1id")

router = APIRouter(prefix="/api/app/files", tags=["File Viewer"])

# Ліміт розміру файлу (узгоджено з лімітом здачі ДЗ — 60 МіБ, N-M10)
MAX_FILE_BYTES = 60 * 1024 * 1024

# Allowlist хостів: файли itstep.org (fs3.itstep.org і родичі) +
# ВЛАСНИЙ домен (M1 Provider: здача через /api/v1/files/<slug> потрапляє
# у file_path як https://<domain>/api/v1/files/<slug>, і без цього
# в'ювер відмовляв показувати власні здачі — файл «не відкривається»).
# SSRF-запобіжник: інші хости заборонені — авторизований користувач не
# має можливості сканувати внутрішню мережу через цей ендпоінт.
_ALLOWED_HOST_SUFFIX = ".itstep.org"
_ALLOWED_ROOT = "itstep.org"


def _own_hosts() -> set[str]:
    """Хости наших M1-коротких посилань: domain, www.domain, m.domain."""
    d = get_settings().domain.lower().strip()
    return {d, f"www.{d}", f"m.{d}"}


def _is_allowed_host(host: str) -> bool:
    return (host == _ALLOWED_ROOT
            or host.endswith(_ALLOWED_HOST_SUFFIX)
            or host in _own_hosts())

# Ходіння за редіректами: лише в межах allowlist, максимум 3 стрибки
_MAX_REDIRECTS = 3

_EXT_MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".txt": "text/plain",
    ".doc": "application/msword",
    ".zip": "application/zip",
    ".docx": ("application/vnd.openxmlformats-officedocument"
              ".wordprocessingml.document"),
}


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ApiError(400, "file_bad_url", "url", "only_http_https_urls_allowed")
    host = (parsed.hostname or "").lower()
    if not _is_allowed_host(host):
        raise ApiError(400, "file_bad_url", "url", "only_itstep_files_allowed")
    if not parsed.path.startswith("/api/v1/files/"):
        raise ApiError(400, "file_bad_url", "url", "only_itstep_files_allowed")
    return url


def _upstream_filename(content_disposition: str, url: str) -> str:
    """Дістаємо назву файлу: RFC 5987 (filename*=, %-кодування — вже
    ASCII-безпечне) має пріоритет; інакше — звичайний filename="..."."""
    m = re.search(r"filename\*=utf-8''([^;]+)",
                  content_disposition, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'filename="?([^";]+)"?', content_disposition)
    if m:
        return m.group(1).strip()
    return urlparse(url).path.rsplit("/", 1)[-1]


def _latin1_safe(name: str) -> str:
    """HTTP-заголовки — latin-1: кирилиця в X-File-Name ламає відповідь
    посередині стріму (клієнт бачить 200 і ERR_FAILED). Не-latin1
    символи процентно кодуємо; фронт розкодовує decodeURIComponent."""
    try:
        name.encode("latin-1")
        return name
    except UnicodeEncodeError:
        return quote(name, safe="")


def _safe_filename(name: str) -> str:
    """Прибираємо все, що могло б зламати заголовок Content-Disposition."""
    cleaned = re.sub(r'[\\\r\n";]+', "_", name).strip()
    return cleaned[:180] or "file"


# Типи, які безпечно показувати inline (браузер не виконує в них скриптів).
# Усе інше — лише attachment; активні типи (html/svg/xml/js…) віддаємо як
# octet-stream, щоб вони не рендерились у origin застосунку.
_INLINE_SAFE = {
    "application/pdf", "image/png", "image/jpeg", "image/webp",
    "image/gif", "text/plain",
}


def _is_active_type(ctype: str) -> bool:
    return (ctype in ("image/svg+xml", "application/xhtml+xml",
                      "application/xml", "application/javascript",
                      "application/x-javascript")
            or ctype.startswith("text/") and ctype != "text/plain"
            or ctype.endswith("+xml"))


def _guess_ctype(resp: httpx.Response, url: str) -> str:
    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype and ctype != "application/octet-stream":
        return ctype
    ext = os.path.splitext(urlparse(url).path.lower())[1]
    return _EXT_MIME.get(ext, "application/octet-stream")


async def _stream_guarded(resp: httpx.Response) -> AsyncIterator[bytes]:
    """Стрімінг тіла з лімітом (захисна межа): при перевищенні
    MAX_FILE_BYTES тихо обриваємо — заголовки вже відправлені, тому
    ApiError тут неможливий (його перевірено ДО старту стріму).
    aiter_raw — байти as-is (просимо Accept-Encoding: identity)."""
    sent = 0
    try:
        async for chunk in resp.aiter_raw():
            sent += len(chunk)
            if sent > MAX_FILE_BYTES:
                _log.warning("fileview: upstream перевищив ліміт під час стріму")
                return
            yield chunk
    finally:
        # Відповідь жива, поки StreamingResponse її читає —
        # закриваємо саме тут (включно з обривом клієнтом).
        await resp.aclose()


async def _stream_spooled(fh) -> AsyncIterator[bytes]:
    """Віддача вже перевіреного за розміром тіла зі spooled-файлу."""
    try:
        while True:
            chunk = fh.read(64 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        fh.close()


@router.get("/view", dependencies=[rate_limit_user(times=60)])
async def view(url: str = Query(..., min_length=8),
               user: User = Depends(get_current_user)):
    """Проксі файлу з fs*.itstep.org: байти as-is для рендера на фронті."""
    target = _validate_url(url)
    current: str = target

    client = ms.shared_async_client()
    resp: httpx.Response | None = None
    for _ in range(_MAX_REDIRECTS + 1):
        try:
            # follow_redirects=False — кожен стрибок перевіряємо
            # вручну проти allowlist (інакше SSRF через 30x).
            # stream=True: НЕ тягнемо весь файл у пам'ять — заголовки
            # віддаємо клієнту одразу, тіло тече крізь нас шматками
            # (23 МБ pdf не повинні лежати в RAM робітника).
            # Accept-Encoding: identity — passthrough без декодування,
            # інакше Content-Length апстрима не збігався б з тілом.
            req = client.build_request(
                "GET", current,
                headers={"User-Agent": "m1id/1.0",
                         "Accept-Encoding": "identity"})
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as e:
            _log.warning("fileview_fail %s: %s", current, type(e).__name__)
            raise ApiError(502, "file_fetch_failed", "url",
                           "file_temporarily_unreachable") from e
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("location", "")
            await resp.aclose()
            if not loc:
                raise ApiError(502, "file_fetch_failed", "url",
                               "file_temporarily_unreachable")
            current = str(httpx.URL(current).join(loc))
            _validate_url(current)
            continue
        break

    assert resp is not None

    if resp.status_code >= 400:
        await resp.aclose()
        raise ApiError(502, "file_fetch_failed", "url",
                       "file_not_found_on_upstream")

    # Заздалегідь відомий завеликий файл — 413 ДО початку стріму
    # (клієнт отримає нормальну помилку, а не обірване тіло).
    pre_len = resp.headers.get("content-length")
    if pre_len and (pre_len.isascii() and pre_len.isdigit()) and int(pre_len) > MAX_FILE_BYTES:
        await resp.aclose()
        raise ApiError(413, "file_too_large", "url", "file_too_large_to_view")

    # Немає Content-Length (chunked): розмір невідомий, а ApiError після
    # початку стріму вже неможливий. Тому спершу вичитуємо тіло в
    # SpooledTemporaryFile (RAM до 4 МіБ, далі диск) з жорстким лімітом
    # і лише потім віддаємо клієнту з відомою довжиною.
    spooled = None
    if not (pre_len and (pre_len.isascii() and pre_len.isdigit())):
        spooled = tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024)
        total = 0
        try:
            async for chunk in resp.aiter_raw():
                total += len(chunk)
                if total > MAX_FILE_BYTES:
                    spooled.close()
                    raise ApiError(413, "file_too_large", "url",
                                   "file_too_large_to_view")
                spooled.write(chunk)
        except httpx.HTTPError as e:
            spooled.close()
            raise ApiError(502, "file_fetch_failed", "url",
                           "file_temporarily_unreachable") from e
        finally:
            await resp.aclose()
        spooled.seek(0)
        pre_len = str(total)

    ctype = _guess_ctype(resp, current)
    fname = _safe_filename(
        _upstream_filename(resp.headers.get("content-disposition", ""), current))

    # Allowlist для inline: лише безпечні типи. Решта (html/svg/xml та
    # невідомі) — attachment; активні типи віддаємо як octet-stream.
    # CSP sandbox забороняє виконання скриптів, навіть якщо файл відкриють.
    inline_ok = ctype in _INLINE_SAFE
    if _is_active_type(ctype):
        ctype = "application/octet-stream"
    disposition = "inline" if inline_ok else "attachment"

    # X-File-Name — фронт показує його і вирішує, як рендерити
    # (docx/zip визначаються за розширенням). nosniff: браузер не вгадує тип.
    headers = {
        "Content-Disposition": f'{disposition}; filename="file"',
        "X-File-Name": _latin1_safe(fname),
        "Cache-Control": "private, max-age=300",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    }
    # Прокидаємо Content-Length апстрима: chunked-відповіді на 20+ МБ
    # через Caddy/Cloudflare обривалися (net::ERR_FAILED 200 у браузері).
    if pre_len and (spooled is not None
                    or not resp.headers.get("content-encoding")):
        headers["Content-Length"] = pre_len

    body = (_stream_spooled(spooled) if spooled is not None
            else _stream_guarded(resp))
    return StreamingResponse(body, media_type=ctype, headers=headers)
