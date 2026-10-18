"""M1 Provider: короткі посилання для здачі ДЗ (links.db).

Чому це працює: mapi не приймає «голий» URL у filename — він дописує
свій префікс /api/v1/files/. Але шлях, що ВЖЕ виглядає як
«<host>/api/v1/files/<token>», він не переписує. Тому в filename ДЗ
підставляємо https://<domain>/api/v1/files/<slug> → вчитель клікає
→ потрапляє на наш роутер, який робить 302 або показує галерею.

Окрема БД links.db (поруч із m1id.db) — ізоляція збоїв, як plugins.db.
Метадані (account_id, homework_id) — для аналітики/аудиту, НЕ для
розмежування доступу: вчитель ходить за посиланням анонімно.

Посилання живуть нескінченно, доки власник сам їх не вилучить.
"""
from __future__ import annotations

import asyncio
import html as _html
import io
import ipaddress
import json
import logging
import random
import secrets
import socket
import string
import threading
import time
import zipfile
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, \
    Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.clock import utc_to_kyiv
from app.core.config import get_settings

_ALPHABET = string.ascii_letters + string.digits  # base62
SLUG_LEN = 8
# скільки пам'ятаємо, що посилання вже «сповістили» (анти-спам у TG)
_NOTIFY_THROTTLE_SECONDS = 300
# кеш розшифрованих/розпакованих медіа-байтів (на відкриття вчителем)
_MEDIA_CACHE_SECONDS = 60

SUPPORTED_EXT = ("png", "jpg", "jpeg", "webp", "mp4", "webm", "zip")


def utcnow() -> datetime:
    """B6: наївний UTC з ЄДИНОГО джерела часу (app.core.clock)."""
    from app.core.clock import naive_utcnow
    return naive_utcnow()


class LinkBase(DeclarativeBase):
    pass


def links_db_path() -> Path:
    main_url = get_settings().db_url
    if main_url.startswith("sqlite"):
        main_path = main_url.split("///")[-1]
        if main_path and main_path != ":memory:":
            p = Path(main_path)
            if not p.is_absolute():
                p = Path.cwd() / p
            return p.parent / "links.db"
    return Path.cwd() / "links.db"


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        path = links_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def _pragma(dbapi_connection, _record):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    return _engine


def new_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(),
                                     autoflush=False, expire_on_commit=False)
    return _SessionLocal()


def init_links_db() -> None:
    LinkBase.metadata.create_all(get_engine())


class M1Link(LinkBase):
    """Коротке посилання /api/v1/files/<slug>.

    kind: "url" (redirect на target_url) | "file" (redirect або галерея).
    media_json: маніфест [{name, ext}] — заповнюється при здачі,
    коли всі файли підтримувані й увімкнено «відкривати в браузері».
    """

    __tablename__ = "m1_links"

    slug = Column(String(16), primary_key=True)
    user_id = Column(Integer, index=True, default=0)
    account_id = Column(Integer, index=True, default=0)
    account_seq = Column(Integer, default=1)
    homework_id = Column(Integer, index=True, default=0)
    hw_title = Column(String(255), default="")
    hw_subject = Column(String(255), default="")
    hw_due = Column(String(32), default="")
    kind = Column(String(8), default="url")
    target_url = Column(Text, default="")
    media_json = Column(Text, default="")
    active = Column(Boolean, default=True)
    opens = Column(Integer, default=0)
    last_opened_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


# ---------------------------------------------------------------- slug / URL

def _random_slug() -> str:
    rng = random.SystemRandom()
    return "".join(rng.choice(_ALPHABET) for _ in range(SLUG_LEN))


def public_base_url() -> str:
    """Хост короткого посилання — m1id.xyz. Патерн /api/v1/files/<slug>
    обраний ПІД формат файлових URL MyStat (mapi не переписує шлях,
    що виглядає як його власний files-патерн) — це стосується лише
    шляху; відкриття веде на наш бекенд."""
    return f"https://{get_settings().domain.lower().strip()}"


def create_link(*, user_id: int = 0, account_id: int = 0,
                account_seq: int = 1, homework_id: int = 0,
                hw_title: str = "", hw_subject: str = "", hw_due: str = "",
                kind: str = "url", target_url: str = "",
                media: list[dict] | None = None) -> M1Link:
    """Створити посилання з перевіркою колізій slug.

    Сесія завжди своя (links.db): головну сесію m1id.db передавати
    не можна — таблиці там немає і INSERT впаде 500-ю."""
    db = new_session()
    try:
        for _ in range(10):
            slug = _random_slug()
            if db.get(M1Link, slug) is None:
                break
        else:
            raise RuntimeError("slug_collision")
        row = M1Link(
            slug=slug, user_id=user_id, account_id=account_id,
            account_seq=account_seq, homework_id=homework_id,
            hw_title=(hw_title or "")[:255], hw_subject=(hw_subject or "")[:255],
            hw_due=(hw_due or "")[:32], kind=kind,
            target_url=target_url,
            media_json=json.dumps(media) if media else "",
            active=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def deactivate_homework(user_id: int, homework_id: int) -> int:
    """Вилучити всі M1-посилання ДЗ (викликається після видалення здачі)."""
    db = new_session()
    try:
        rows = (db.query(M1Link)
                .filter(M1Link.user_id == user_id,
                        M1Link.homework_id == homework_id)
                .all())
        n = 0
        for r in rows:
            if r.active:
                r.active = False
                n += 1
        db.commit()
        return n
    finally:
        db.close()


async def upload_fs_file(account, filename: str, data: bytes,
                         content_type: str | None) -> str:
    """Завантажити файл у fs itstep (той самий контракт, що при здачі:
    GET /user/file-token → POST multipart) → пряме посилання."""
    import httpx

    from app.core.responses import ApiError
    # H2 fix: реальні модулі (раніше імпортувалися неіснуючі
    # app.services.mystat / app.services.crypto → ImportError → 500)
    from app.core.security import decrypt_secret
    from app.services import mystat_client as ms

    token = decrypt_secret(account.access_token_enc)
    alias = account.branch_alias
    language = account.language or "uk"
    uid = account.id_user_storage or None

    r = await ms.request_async(
        "GET", f"/v1/mystat/{alias}/user/file-token",
        token=token, language=language, user_id=uid)
    if r.status_code != 200:
        raise ApiError(502, "mystat_unavailable", "__all__",
                       f"file_token_status_{r.status_code}")
    try:
        ft = r.json()
    except Exception:
        ft = None
    if not isinstance(ft, dict):
        ft = {}
    furl = ft.get("url") or ""
    hwdir = (ft.get("directories") or {}).get("homeworkDirId") or ""
    ftoken = ft.get("token") or ""
    if not furl or not hwdir or not ftoken:
        raise ApiError(502, "mystat_unavailable", "__all__",
                       "file_service_unconfigured")
    up_timeout = httpx.Timeout(120.0, connect=15.0)
    async with httpx.AsyncClient(transport=ms._async_transport,
                                 timeout=up_timeout) as fx:
        up = await fx.post(
            furl,
            files=[("files[]", (filename, data,
                                content_type or "application/octet-stream"))],
            data={"directory": hwdir},
            headers={"Authorization": f"Bearer {ftoken}",
                     "X-Language": language})
    if up.status_code not in (200, 201):
        raise ApiError(502, "mystat_unavailable", "__all__",
                       f"file_upload_status_{up.status_code}")
    try:
        out = [x["link"] for x in up.json()
               if isinstance(x, dict) and x.get("link")]
    except Exception:
        out = []
    if not out:
        raise ApiError(502, "mystat_unavailable", "__all__",
                       "file_upload_empty")
    return out[0]


async def delete_fs_file(account, link: str) -> bool:
    """Спроба видалити файл з fs itstep (best-effort).

    Документований контракт: `DELETE {url}/{path}` з fs-токеном. Точний
    шлях не підтверджено, тому пробуємо кілька кандидатів, усі прив'язані
    до ключа файлу; перший 2xx — успіх. Будь-яка помилка → False (файл у
    нас усе одно видаляється, на fs він може лишитись)."""
    import httpx
    from urllib.parse import urlparse

    from app.core.security import decrypt_secret
    from app.services import mystat_client as ms

    try:
        pu = urlparse(link)
        host = (pu.hostname or "").lower()
        key = pu.path.rstrip("/").rsplit("/", 1)[-1]
        if not key or not (host == "itstep.org" or host.endswith(".itstep.org")):
            return False
        token = decrypt_secret(account.access_token_enc)
        alias = account.branch_alias
        language = account.language or "uk"
        r = await ms.request_async(
            "GET", f"/v1/mystat/{alias}/user/file-token",
            token=token, language=language,
            user_id=account.id_user_storage or None)
        ft = r.json() if r.status_code == 200 else None
        if not isinstance(ft, dict) or not ft.get("url") or not ft.get("token"):
            return False
        furl = str(ft["url"]).rstrip("/")
        hwdir = str((ft.get("directories") or {}).get("homeworkDirId") or "")
        candidates = [link, f"{furl}/{key}"]
        if hwdir:
            candidates.append(f"{furl}/{hwdir}/{key}")
        headers = {"Authorization": f"Bearer {ft['token']}", "X-Language": language}
        async with httpx.AsyncClient(transport=ms._async_transport,
                                     timeout=httpx.Timeout(20.0, connect=10.0)) as fx:
            for url in dict.fromkeys(candidates):
                try:
                    res = await fx.delete(url, headers=headers)
                except httpx.HTTPError:
                    continue
                if 200 <= res.status_code < 300:
                    return True
        return False
    except Exception:  # best-effort: збій fs не повинен ламати видалення
        _log.warning("fs delete failed for %s", link, exc_info=True)
        return False


def public_url(row: M1Link) -> str:
    return f"{public_base_url()}/api/v1/files/{row.slug}"


def link_view(row: M1Link) -> dict:
    """Серіалізація для /api/links (фронт: статистика, редагування)."""
    media = None
    try:
        media = json.loads(row.media_json) if row.media_json else None
    except Exception:
        media = None
    return {
        "slug": row.slug,
        "url": public_url(row),
        "kind": row.kind,
        "target_url": row.target_url,
        "homework_id": row.homework_id,
        "hw_title": row.hw_title,
        "hw_subject": row.hw_subject,
        "media": media,
        "gallery": bool(media),
        "active": row.active,
        "opens": row.opens,
        # N-M9 fix: часові мітки віддаємо клієнту у київському часі
        # (у БД лишаються наївним UTC).
        "last_opened_at": utc_to_kyiv(row.last_opened_at).isoformat()
        if row.last_opened_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ------------------------------------------------------- медіа: сниф + кеш

def _sniff(data: bytes) -> str:
    """Content-type за магічними байтами (довіряємо файлу, не імені)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        return "video/mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    return ""


def is_supported_name(name: str) -> bool:
    ext = (name or "").rsplit(".", 1)[-1].lower()
    return ext in SUPPORTED_EXT


def build_media_manifest(files: list[tuple[str, bytes, str]]) -> list[dict] | None:
    """Маніфест галереї зі зданих файлів: [] якщо щось не підтримується.
    .zip → вкладені файли теж мусять бути зображеннями/відео."""
    media: list[dict] = []
    for name, data, _ct in files:
        base = (name or "file").rsplit("\\", 1)[-1]
        ext = base.rsplit(".", 1)[-1].lower()
        if ext in ("png", "jpg", "jpeg", "webp", "mp4", "webm"):
            media.append({"name": base, "ext": ext})
        elif ext == "zip":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    inner = [i for i in _zip_check(zf)
                             if not i.is_dir() and not i.filename
                             .rsplit("/", 1)[-1].startswith(".")]
                if not inner:
                    return None
                for i in inner:
                    iname = i.filename.rsplit("/", 1)[-1]
                    iext = iname.rsplit(".", 1)[-1].lower()
                    if iext not in ("png", "jpg", "jpeg", "webp"):
                        return None
                    media.append({"name": iname, "ext": iext,
                                  "zip": base})
            except Exception:
                return None
        else:
            return None
    return media or None


# H3 fix: кеш — OrderedDict (LRU) з СУМАРНИМ лімітом RAM (~100МБ),
# а не «24 записи × до 25МБ» (до 600МБ у пам'яті процесу).
_MEDIA_CACHE_MAX_BYTES = 100 * 1024 * 1024
_media_cache: "OrderedDict[str, tuple[float, bytes, str]]" = OrderedDict()
_media_cache_bytes = 0
_media_lock = threading.Lock()
# Один AsyncClient на процес: анонімні /media і /download не блокують
# event loop синхронним httpx (синхронний клієнт в async-роуті = self-DoS).
_dl: httpx.AsyncClient | None = None
_dl_lock = threading.Lock()


def _dl_client() -> httpx.AsyncClient:
    global _dl
    with _dl_lock:
        if _dl is None or _dl.is_closed:
            _dl = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                limits=httpx.Limits(max_connections=20,
                                    max_keepalive_connections=10))
        return _dl


async def close_dl_client() -> None:
    """Graceful shutdown спільного клієнта завантажень (викликається з lifespan)."""
    global _dl
    with _dl_lock:
        if _dl is not None and not _dl.is_closed:
            await _dl.aclose()
        _dl = None


def _cached(key: str) -> tuple[bytes, str] | None:
    with _media_lock:
        hit = _media_cache.get(key)
        if hit and time.monotonic() - hit[0] < _MEDIA_CACHE_SECONDS:
            _media_cache.move_to_end(key)  # LRU: нещодавно вжите — в кінець
            return hit[1], hit[2]
        if hit:
            _media_cache.pop(key, None)
    return None


def _store(key: str, data: bytes, ctype: str) -> None:
    global _media_cache_bytes
    with _media_lock:
        prev = _media_cache.pop(key, None)
        if prev is not None:
            _media_cache_bytes -= len(prev[1])
        _media_cache[key] = (time.monotonic(), data, ctype)
        _media_cache_bytes += len(data)
        # витісняємо найстаріші (LRU), поки сумарний розмір не вкладеться
        while _media_cache_bytes > _MEDIA_CACHE_MAX_BYTES and _media_cache:
            _, (__, old_data, ___) = _media_cache.popitem(last=False)
            _media_cache_bytes -= len(old_data)


class UnsafeUrl(ValueError):
    """Цільовий URL заборонений (схема/порт/приватна адреса) — захист від SSRF."""


class FetchTooLarge(ValueError):
    """Відповідь перевищила ліміт байтів."""


# ліміти завантаження чужого URL / розпакування (захист від DoS)
_FETCH_MAX_BYTES = 50 * 1024 * 1024
_FETCH_MAX_REDIRECTS = 3
_ZIP_MAX_ENTRIES = 200
_ZIP_MAX_TOTAL_UNCOMPRESSED = 200 * 1024 * 1024
_ZIP_MAX_MEMBER = 25 * 1024 * 1024
_ALLOWED_PORTS = (None, 80, 443)

# хости itstep, на які безпечно редіректити без проміжної сторінки
_TRUSTED_REDIRECT_SUFFIXES = ("itstep.org",)


def is_trusted_redirect_host(url: str) -> bool:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not host:
        return False
    return any(host == suf or host.endswith("." + suf)
               for suf in _TRUSTED_REDIRECT_SUFFIXES)


def check_url_syntax(url: str) -> str:
    """Лише синтаксична перевірка (http/https, хост, порт). Повертає хост."""
    try:
        parts = urlsplit((url or "").strip())
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrl("bad_url") from exc
    if parts.scheme not in ("http", "https") or not host:
        raise UnsafeUrl("scheme_not_allowed")
    if parts.username or parts.password:
        raise UnsafeUrl("userinfo_not_allowed")
    if port not in _ALLOWED_PORTS:
        raise UnsafeUrl("port_not_allowed")
    return host


async def assert_public_url(url: str) -> None:
    """SSRF-захист: хост мусить резолвитись ЛИШЕ у глобальні адреси
    (не loopback/private/link-local/metadata/reserved).
    Примітка: між перевіркою і з'єднанням можливий DNS-rebinding;
    повністю закриває лише pinning IP на рівні транспорту."""
    host = check_url_syntax(url)
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise UnsafeUrl("dns_failed") from exc
        ips = []
        for info in infos:
            try:
                ips.append(ipaddress.ip_address(info[4][0].split("%")[0]))
            except ValueError:
                continue
    if not ips:
        raise UnsafeUrl("no_address")
    for ip in ips:
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise UnsafeUrl("private_address")


async def fetch_bytes(url: str,
                      max_bytes: int = _FETCH_MAX_BYTES) -> tuple[bytes, str]:
    """Завантажити файл → (bytes, type) зі стрімінгом і лімітом розміру.

    H3 fix: async-версія — не блокує event loop під час 60с-завантажень.
    Безпека: кожен хоп (включно з редіректами, що йдуть вручну)
    перевіряється assert_public_url; розмір обмежено max_bytes."""
    client = _dl_client()
    cur = url
    for _ in range(_FETCH_MAX_REDIRECTS + 1):
        await assert_public_url(cur)
        async with client.stream("GET", cur, follow_redirects=False) as r:
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("location")
                if not loc:
                    raise UnsafeUrl("redirect_without_location")
                cur = str(httpx.URL(cur).join(loc))
                continue
            r.raise_for_status()
            cl = r.headers.get("content-length")
            if cl and (cl.isascii() and cl.isdigit()) and int(cl) > max_bytes:
                raise FetchTooLarge("content_length_exceeds_limit")
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise FetchTooLarge("body_exceeds_limit")
            ctype = (r.headers.get("content-type") or "").split(";")[0]
            return bytes(buf), ctype
    raise UnsafeUrl("too_many_redirects")


def _zip_check(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Ліміти проти zip-бомби: кількість записів і сумарний розпакований розмір."""
    infos = zf.infolist()
    if len(infos) > _ZIP_MAX_ENTRIES:
        raise FetchTooLarge("zip_too_many_entries")
    if sum(i.file_size for i in infos) > _ZIP_MAX_TOTAL_UNCOMPRESSED:
        raise FetchTooLarge("zip_too_large_uncompressed")
    return infos


class MediaIndexError(LookupError):
    """Індекс поза межами маніфеста (→ 404, а не IndexError → 502)."""
    pass


async def media_for(row: M1Link, index: int) -> tuple[bytes, str]:
    """Розкритий байт-потік елемента маніфесту + content-type.

    Кеш 60 с, щоб не качати файл з STEP на кожне відкриття/перемикання.
    Невідомий тип (не впізнали магічні байти) → ValueError → фронт
    покаже «Помилка» / кнопка Скачати як fallback.
    Індекс поза маніфестом → MediaIndexError (роутер віддає 404)."""
    try:
        media = json.loads(row.media_json)
        item = media[index]
    except (ValueError, TypeError, IndexError, KeyError) as exc:
        raise MediaIndexError(f"bad media index {index}") from exc
    cache_key = f"{row.slug}:{index}"
    hit = _cached(cache_key)
    if hit:
        return hit
    if item.get("zip"):
        # байти батьківського архіва = target (це і є .zip) → вирвати
        # елемент. У маніфесті сам архів не значиться, шукати там нічого.
        # кеш самого архіва: кілька елементів галереї → 1 завантаження
        zb = None
        hit_z = _cached(f"{row.slug}:zip")
        if hit_z:
            zb, _ = hit_z
        else:
            zb, _ = await fetch_bytes(row.target_url)
            _store(f"{row.slug}:zip", zb, "application/zip")
        with zipfile.ZipFile(io.BytesIO(zb)) as zf:
            _zip_check(zf)
            match = next((i for i in zf.infolist()
                          if not i.is_dir()
                          and i.filename.rsplit("/", 1)[-1] == item["name"]),
                         None)
            if match is None:
                raise MediaIndexError(f"item not in archive: {item['name']}")
            if match.file_size > _ZIP_MAX_MEMBER:
                raise FetchTooLarge("zip_member_too_large")
            # читаємо з жорстким лімітом, не довіряючи заголовку
            with zf.open(match) as fh:
                data = fh.read(_ZIP_MAX_MEMBER + 1)
            if len(data) > _ZIP_MAX_MEMBER:
                raise FetchTooLarge("zip_member_too_large")
    else:
        data, _ct = await fetch_bytes(row.target_url)
    ctype = _sniff(data)
    if not ctype:
        raise ValueError("unsupported_content")
    _store(cache_key, data, ctype)
    return data, ctype


# ---------------------------------------------------------------- відкриття

def register_open(row: M1Link,
                  loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Інкремент статистики + сповіщення в TG (з тротлінгом).

    B5 fix: атомарний UPDATE на місці (opens=opens+1) — конкурентні
    відкриття не гублять інкременти й не перезаписують рядок
    застарілим знімком об'єкта (було: merge у нову сесію).

    Функція виконується у worker-потоці (asyncio.to_thread), тому loop
    треба передавати ЯВНО: у потоці get_running_loop() не працює."""
    now = utcnow()
    db = new_session()
    try:
        from sqlalchemy import update as _sa_update

        db.execute(_sa_update(M1Link)
                   .where(M1Link.slug == row.slug)
                   .values(opens=M1Link.opens + 1, last_opened_at=now))
        db.commit()
    finally:
        db.close()
    row.opens += 1
    row.last_opened_at = now
    _maybe_notify(row, loop)


# тротлінг сповіщень у пам'яті процесу (перезапуск скине — не страшно).
# LOW fix: обмежений LRU-словник, а не вічний ріст пам'яті.
_NOTIFY_THROTTLE_MAX = 512
_notify_last: "OrderedDict[str, float]" = OrderedDict()
_notify_inflight: set[str] = set()
_notify_lock = threading.Lock()
# сильні посилання на фонові задачі (інакше GC може їх зібрати до завершення)
_notify_tasks: "set[asyncio.Task]" = set()
_log = logging.getLogger("m1id.links")


def _maybe_notify(row: M1Link,
                  loop: asyncio.AbstractEventLoop | None = None) -> None:
    if not (row.homework_id and row.user_id):
        return
    # тумблер користувача: сповіщати чи ні (notify_link_open, дефолт УВІМК)
    from app.db.base import SessionLocal
    from app.db.models import TelegramAccountConfig

    db = SessionLocal()
    try:
        cfg = (db.query(TelegramAccountConfig)
               .filter(TelegramAccountConfig.account_id == row.account_id)
               .first())
        if cfg is not None and not cfg.notify_link_open:
            return
    finally:
        db.close()
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
    # слот тротлінгу тут лише ПЕРЕВІРЯЄМО; фіксується після успішної відправки
    with _notify_lock:
        last = _notify_last.get(row.slug)
        if last is not None and time.monotonic() - last < _NOTIFY_THROTTLE_SECONDS:
            return
        if row.slug in _notify_inflight:
            return
        _notify_inflight.add(row.slug)
    try:
        loop.call_soon_threadsafe(_spawn_notify, row)
    except RuntimeError:  # loop уже закритий
        with _notify_lock:
            _notify_inflight.discard(row.slug)


def _spawn_notify(row: M1Link) -> None:
    """Виконується в потоці event loop: створює задачу й тримає посилання."""
    task = asyncio.get_running_loop().create_task(_send_notify(row))
    _notify_tasks.add(task)
    task.add_done_callback(_notify_tasks.discard)


def _mark_notified(slug: str) -> None:
    with _notify_lock:
        _notify_last[slug] = time.monotonic()
        _notify_last.move_to_end(slug)
        # LOW fix: обмежуємо розмір тротлінг-словника (LRU-витіснення)
        while len(_notify_last) > _NOTIFY_THROTTLE_MAX:
            _notify_last.popitem(last=False)


async def _send_notify(row: M1Link) -> None:
    """📚 «Ваше завдання перевіряють» + ті самі кнопки, що й у ДЗ."""
    try:
        from app.telegram import bot as bot_mod
        from app.telegram import runtime as tg_runtime

        if not tg_runtime.is_running():
            return
        esc = _html.escape
        title = row.hw_title or f"ДЗ #{row.homework_id}"
        lines = ["📚 <b>Ваше завдання перевіряють</b>"]
        # логін акаунта (як у poller), якщо акаунтів кілька
        acc_login = ""
        if row.account_seq > 1:
            from app.db.base import SessionLocal as _SL
            from app.db.models import MystatAccount

            _db = _SL()
            try:
                acc = (_db.query(MystatAccount)
                       .filter(MystatAccount.user_id == row.user_id,
                               MystatAccount.user_seq == row.account_seq)
                       .first())
                if acc is not None:
                    acc_login = (acc.mystat_login or acc.label or acc.fio
                                 or f"Акаунт #{row.account_seq}")
            finally:
                _db.close()
            if acc_login:
                lines.append(f"👤 <b>{esc(str(acc_login))}</b>")
        lines.append(esc(f"{row.hw_subject or ''} — {title}".strip(" —")))
        kb = bot_mod.notify_hw_kb(row.homework_id, row.account_seq)
        text = "\n".join(lines)
        # знайти chat користувача
        from app.db.base import SessionLocal
        from app.db.models import TelegramLink

        db = SessionLocal()
        try:
            link = (db.query(TelegramLink)
                    .filter(TelegramLink.user_id == row.user_id).first())
        finally:
            db.close()
        if link is None or not link.chat_id:
            return
        await bot_mod.send_text(link.chat_id, text, kb)
        _mark_notified(row.slug)  # слот тротлінгу — лише після успіху
    except Exception:
        _log.warning("tg notify for %s failed", row.slug, exc_info=True)
    finally:
        with _notify_lock:
            _notify_inflight.discard(row.slug)


# ---------------------------------------------------------------- сторінки

_ERR_PAGE = """<!doctype html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>M1 ID</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;
background:#0B0E14;color:#8b93a7;font:14px/1.5 Inter,system-ui,sans-serif}
.c{text-align:center;padding:32px}.ico{font-size:40px;margin-bottom:10px}
b{color:#e7eaf3;font-size:16px}</style></head><body><div class="c">
<div class="ico">{icon}</div><b>{title}</b><p>{msg}</p></div></body></html>"""


def _err_page(title: str, msg: str, icon: str = "😕",
              status: int = 502) -> HTMLResponse:
    """Сторінка помилки; HTTP-статус задається ЯВНО (не з тексту)."""
    page = (_ERR_PAGE.replace("{icon}", icon)
            .replace("{title}", title).replace("{msg}", msg))
    return HTMLResponse(page, status_code=status,
                        headers={"X-Content-Type-Options": "nosniff"})


_GALLERY_CSS = """
:root{--bg:#0D1017;--panel:#151923;--border:rgba(255,255,255,.07);
--text:#E8EAF0;--dim:#9AA1B2;--accent:#5B7CFA;--radius:16px}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.5 Inter,system-ui,-apple-system,sans-serif;
display:flex;flex-direction:column;overflow:hidden}
header{display:flex;align-items:center;gap:12px;padding:10px 16px;
background:var(--bg);border-bottom:1px solid var(--border);flex-shrink:0}
.hd{min-width:0;flex:1}
.brand{display:block;color:var(--dim);font-size:11px;font-weight:600;
letter-spacing:.06em;text-transform:uppercase;margin-bottom:2px}
.hd>b{display:block;font-size:15px;font-weight:600;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}
.hd small{color:var(--dim);font-size:12px}
.dl{display:inline-flex;align-items:center;gap:7px;padding:9px 16px;
border:none;border-radius:11px;background:var(--accent);
color:#fff;font:inherit;font-weight:600;font-size:13px;cursor:pointer;
text-decoration:none;flex-shrink:0;transition:filter .12s}
.dl:hover{filter:brightness(1.12)}
.dl:active{filter:brightness(.92)}
.bk{display:inline-flex;align-items:center;justify-content:center;width:38px;
height:38px;border:none;border-radius:11px;background:var(--panel);
color:var(--text);font:inherit;font-size:18px;cursor:pointer;flex-shrink:0;
transition:background .12s}
.bk:hover{background:#1C2130}

/* каркас: viewer займає весь вільний простір, панель знизу — фіксована */
main{flex:1;display:flex;flex-direction:column;min-height:0}
.viewer{flex:1;min-height:0;display:flex;align-items:center;
justify-content:center;position:relative;padding:14px}
.stage{position:relative;flex:1;min-width:0;height:100%;display:flex;
align-items:center;justify-content:center;overflow:hidden;
border-radius:var(--radius);background:var(--panel)}
.stage::after{content:"";position:absolute;inset:0;margin:auto;width:28px;
height:28px;border-radius:50%;border:3px solid rgba(91,124,250,.2);
border-top-color:var(--accent);animation:spin .8s linear infinite;
opacity:0;transition:opacity .15s;pointer-events:none}
.stage.load::after{opacity:1}
@keyframes spin{to{transform:rotate(360deg)}}
.stage img,.stage video{display:block;max-width:100%;max-height:100%;
width:auto;height:auto;object-fit:contain;user-select:none;-webkit-user-drag:none;
transform-origin:center;transition:transform .12s ease-out,opacity .2s;
will-change:transform;border-radius:var(--radius)}
.stage.load img,.stage.load video{opacity:0}
video{width:min(90vw,960px)}
.nav{display:flex;gap:8px;flex-shrink:0}
.nav button{width:40px;height:40px;border-radius:50%;
border:none;background:var(--panel);backdrop-filter:blur(6px);
color:var(--text);font-size:17px;cursor:pointer;
display:grid;place-items:center;transition:background .12s}
.nav button:hover{background:#1D2330}
.nav button:disabled{opacity:.22;cursor:default}

/* нижня панель: жорстко приклеєна до низу */
.bar{flex-shrink:0;margin-top:auto;display:flex;flex-direction:column;
gap:2px;background:var(--bg);border-top:1px solid var(--border);
padding:6px 12px calc(8px + env(safe-area-inset-bottom))}
.brow{display:flex;align-items:center;justify-content:space-between;gap:10px}
.cnt{color:var(--dim);font-size:12px;padding:4px 2px;
font-variant-numeric:tabular-nums;flex-shrink:0}
.tools{display:flex;gap:8px}
.tools button{width:42px;height:36px;border:none;border-radius:11px;
background:var(--panel);color:var(--text);font:inherit;font-size:15px;
cursor:pointer;transition:background .12s}
.tools button:hover{background:#1D2330}
.tools button.on{color:var(--accent);background:#1A2033}
.strip{display:flex;gap:8px;padding:8px 2px 4px;overflow-x:auto;
justify-content:flex-start;scrollbar-width:thin;
scrollbar-color:#2A3142 transparent}
.strip::-webkit-scrollbar{height:6px}
.strip::-webkit-scrollbar-thumb{background:#2A3142;border-radius:3px}
.strip img,.strip .vth{width:64px;height:48px;object-fit:cover;
border-radius:9px;border:2px solid transparent;cursor:pointer;
opacity:.5;transition:opacity .12s,border-color .12s;background:#000;
flex-shrink:0}
.strip .vth{display:grid;place-items:center;font-size:18px}
.strip .act{border-color:var(--accent);opacity:1}

@media(max-width:640px){
  header{padding:8px 10px;gap:8px}
  .dl{padding:8px 12px;font-size:12px}
  .bk{width:34px;height:34px}
  .nav button{width:36px;height:36px}
  .viewer{padding:10px}
  .tools button{width:38px;height:34px}
  .strip img,.strip .vth{width:54px;height:40px}
}
"""

_GALLERY_JS = """
const stage=document.getElementById('stage');
const cnt=document.getElementById('cnt');
const strip=document.getElementById('strip');
const items=window.M1_MEDIA;
const BASE=window.M1_BASE;
let media=document.getElementById('media');
let cur=0,scale=1,rot=0,px=0,py=0;

function apply(){media.style.transform=
`translate(${px}px,${py}px) scale(${scale}) rotate(${rot}deg)`;}
function reset(){scale=1;rot=0;px=0;py=0;apply();}
function show(i){
  cur=Math.max(0,Math.min(items.length-1,i));
  const it=items[cur];
  if(it===lastShown&&media.src.endsWith('/media/'+cur))return void sync();
  lastShown=it;
  reset();
  if(it.ext==='mp4'||it.ext==='webm'){
    media.outerHTML=`<video id="media" src="${BASE}/media/${cur}" controls autoplay playsinline></video>`;
  }else{
    media.outerHTML=`<img id="media" src="${BASE}/media/${cur}" alt="">`;
  }
  media=document.getElementById('media');
  media.addEventListener('load',()=>stage.classList.remove('load'));
  media.addEventListener('error',()=>stage.classList.remove('load'));
  if(it.ext!=='mp4'&&it.ext!=='webm'&&!media.complete)stage.classList.add('load');
  bindPan();
  sync();
}
let lastShown=null;
function sync(){
  cnt.textContent=(cur+1)+' / '+items.length;
  [...strip.children].forEach((el,j)=>el.classList.toggle('act',j===cur));
  const act=strip.children[cur];if(act)act.scrollIntoView({block:'nearest',inline:'nearest'});
  document.getElementById('prev').disabled=cur===0;
  document.getElementById('next').disabled=cur===items.length-1;
}
function bindPan(){
  let drag=null;
  media.addEventListener('dblclick',()=>{if(scale>1)reset();else{scale=2.4;apply();}});
  media.addEventListener('pointerdown',e=>{if(scale<=1)return;drag={x:e.clientX-px,y:e.clientY-py};media.setPointerCapture(e.pointerId);});
  media.addEventListener('pointermove',e=>{if(!drag)return;px=e.clientX-drag.x;py=e.clientY-drag.y;apply();});
  media.addEventListener('pointerup',()=>drag=null);
  media.addEventListener('wheel',e=>{e.preventDefault();scale=Math.min(8,Math.max(1,scale*(e.deltaY<0?1.15:0.87)));if(scale===1)reset();else apply();},{passive:false});
}
document.getElementById('prev').onclick=()=>show(cur-1);
document.getElementById('next').onclick=()=>show(cur+1);
document.getElementById('zin').onclick=()=>{scale=Math.min(8,scale*1.3);apply();};
document.getElementById('zout').onclick=()=>{scale=Math.max(1,scale/1.3);if(scale<=1)reset();else apply();};
document.getElementById('rot').onclick=()=>{rot=(rot+90)%360;apply();
  document.getElementById('rot').classList.toggle('on',rot!==0);};
document.getElementById('rst').onclick=reset;
stage.addEventListener('touchstart',e=>{if(e.touches.length===2){const d=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);pinch={d,s:scale};}else pinch=null;},{passive:true});
let pinch=null;
stage.addEventListener('touchmove',e=>{if(pinch&&e.touches.length===2){const d=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);scale=Math.min(8,Math.max(1,pinch.s*d/pinch.d));apply();}},{passive:true});
// свайп між фото (тільки без зуму)
let sx=null,sy=null;
stage.addEventListener('touchstart',e=>{if(e.touches.length===1){sx=e.touches[0].clientX;sy=e.touches[0].clientY;}},{passive:true});
stage.addEventListener('touchend',e=>{
  if(sx===null||scale>1)return;
  const dx=e.changedTouches[0].clientX-sx,dy=e.changedTouches[0].clientY-sy;
  if(Math.abs(dx)>50&&Math.abs(dx)>Math.abs(dy)*1.5)show(cur+(dx<0?1:-1));
  sx=null;},{passive:true});
addEventListener('keydown',e=>{
  if(e.key==='ArrowLeft')show(cur-1);
  if(e.key==='ArrowRight')show(cur+1);
  if(e.key==='0')reset();});
items.forEach((it,i)=>{
  const el=document.createElement(it.ext==='mp4'||it.ext==='webm'?'div':'img');
  if(el.tagName==='DIV'){el.className='vth';el.textContent='▶';}
  else el.src=`${BASE}/media/${i}`;
  el.title=it.name;el.onclick=()=>show(i);strip.appendChild(el);});
show(0);
"""


def _json_for_script(obj) -> str:
    """JSON, безпечний для вбудови в <script>: екранує <, >, & та U+2028/9."""
    return (json.dumps(obj)
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _gallery_page(row: M1Link) -> HTMLResponse:
    _h = _html
    nonce = secrets.token_urlsafe(16)

    media = json.loads(row.media_json)
    items = [{"name": m["name"], "ext": m["ext"]} for m in media]
    title = _h.escape(row.hw_title or "Розв'язок")
    subj = _h.escape(row.hw_subject or "")
    body = f"""<!doctype html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — M1 ID</title>
<style>{_GALLERY_CSS}</style></head><body>
<header>
  <button class="bk" id="bk" title="Повернутися"
    aria-label="Повернутися" style="display:none">←</button>
  <div class="hd"><span class="brand">M1 Provider</span><b>{title}</b><small>{subj}</small></div>
  <a class="dl" href="/api/v1/files/{row.slug}/download" download>Скачати</a>
</header>
<main>
  <div class="viewer">
    <div class="nav"><button id="prev" aria-label="Назад">‹</button></div>
    <div class="stage" id="stage">
      <img id="media" src="" alt="">
    </div>
    <div class="nav"><button id="next" aria-label="Далі">›</button></div>
  </div>
  <div class="bar">
    <div class="brow">
      <div class="cnt" id="cnt"></div>
      <div class="tools">
        <button id="zin" title="Збільшити">＋</button><button id="zout" title="Зменшити">－</button>
        <button id="rot" title="Повернути">⟳</button><button id="rst" title="Скинути">⤢</button>
      </div>
    </div>
    <div class="strip" id="strip"></div>
  </div>
</main>
<script nonce="{nonce}">window.M1_MEDIA={_json_for_script(items)};window.M1_BASE=window.location.pathname;
document.getElementById('bk').onclick=function(){{history.back();}};
if (history.length > 1 || document.referrer)
  document.getElementById('bk').style.display='';</script>
<script nonce="{nonce}">{_GALLERY_JS}</script></body></html>"""
    csp = ("default-src 'none'; script-src 'nonce-" + nonce + "'; "
           "style-src 'unsafe-inline'; img-src 'self' data:; "
           "media-src 'self'; connect-src 'self'; base-uri 'none'; "
           "form-action 'none'; frame-ancestors 'none'")
    return HTMLResponse(body, headers={
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer"})


def _redirect_or_interstitial(target: str) -> Response:
    """Редірект лише на довірені хости itstep.org; інакше — проміжна
    сторінка з явним підтвердженням (захист від open redirect)."""
    if is_trusted_redirect_host(target):
        return RedirectResponse(target, status_code=302)
    try:
        check_url_syntax(target)
    except UnsafeUrl:
        return _err_page("Некоректне посилання",
                         "Ціль цього посилання недійсна.", "⚠️", status=400)
    safe = _html.escape(target, quote=True)
    host = _html.escape(urlsplit(target).hostname or "", quote=True)
    page = f"""<!doctype html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>M1 ID</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;
background:#0B0E14;color:#8b93a7;font:14px/1.5 Inter,system-ui,sans-serif}}
.c{{text-align:center;padding:32px;max-width:560px}}
b{{color:#e7eaf3;font-size:16px}}
p{{word-break:break-all}}
a.go{{display:inline-block;margin-top:12px;padding:10px 18px;border-radius:11px;
background:#5B7CFA;color:#fff;text-decoration:none;font-weight:600}}
</style></head><body><div class="c"><div style="font-size:40px">🔗</div>
<b>Перехід на зовнішній сайт</b>
<p>Це посилання веде на <b>{host}</b>. M1 ID не контролює його вміст.</p>
<p>{safe}</p>
<a class="go" rel="noopener noreferrer nofollow" href="{safe}">Перейти</a>
</div></body></html>"""
    return HTMLResponse(page, headers={
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                   "base-uri 'none'; form-action 'none'; "
                                   "frame-ancestors 'none'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer"})


def handle_open(row: M1Link, want_download: bool = False,
                loop: asyncio.AbstractEventLoop | None = None) -> Response:
    """Головна логіка відкриття: redirect (дефолт) або галерея.

    Галерея лише якщо: kind=file, маніфест є (усі файли підтримані +
    галочка при здачі) і це не пряме скачування.
    loop — event loop для TG-сповіщення (виклик іде з worker-потоку)."""
    if not row.active:
        return _err_page("Посилання вилучено",
                         "Власник деактивував це посилання.", "🔒",
                         status=410)
    register_open(row, loop)
    if want_download and row.kind == "file":
        # пряме скачування оригіналу з fs-сервера itstep
        return _redirect_or_interstitial(row.target_url)
    if row.kind == "url" or not row.media_json:
        return _redirect_or_interstitial(row.target_url)
    return _gallery_page(row)


async def handle_media(row: M1Link, index: int) -> Response:
    try:
        data, ctype = await media_for(row, index)
    except MediaIndexError:
        # H3 fix: неіснуючий індекс медіа — чесна 404, а не IndexError/502
        return _err_page("Не знайдено",
                         "Такого елемента в галереї немає.", "🔍", status=404)
    except Exception:
        return _err_page("Помилка",
                         "Не вдалося отримати файл. Спробуйте ще раз "
                         "або скачайте оригінал.", "⚠️")
    return Response(content=data, media_type=ctype,
                    headers={"Cache-Control": "private, max-age=60",
                             "X-Content-Type-Options": "nosniff"})
