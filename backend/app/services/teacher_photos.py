"""Збирач фото викладачів.

API MyStat не віддає фото викладачів у контактах — вони є лише у відповідях
оцінок (`fio_teach` + `photo_pas`) і ДЗ (`id_teach` + `fio_teach` +
`teach_photo_pas`). Коли ці відповіді йдуть через наш сервер (хук
app_data.on_fresh_data), окремою фоновою задачею перевіряємо, чи є в них
фото, яких у нас ще немає, і зберігаємо їх (таблиця teacher_photos + файли
в settings.teacher_photos_dir).

Швидкість:
  • усі відомі фото тримаємо в оперативній пам'яті (індекси нижче), тож
    перевірка відповіді — кілька dict-lookup'ів без БД і без мережі;
  • один акаунт перевіряємо не частіше ніж раз на 24 години;
  • усе важке (БД, файли, завантаження) — поза запитом користувача:
    слухач on_fresh_data виконується окремою asyncio-задачею, БД і файли —
    у пулі потоків (asyncio.to_thread).

Прив'язка: філія + ПІБ (як прийшло з MyStat, разом із «School» — на бекенді
не ріжемо), id викладача (з ДЗ або з контактів) і посилання MyStat: воно
генерується випадково, тож нове посилання = викладач змінив фото."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import BASE_DIR, get_settings
from app.db.base import SessionLocal
from app.db.models import MystatAccount, Snapshot, TeacherPhoto, utcnow

_log = logging.getLogger("m1id.teachers")

# Як часто перевіряти ОДИН акаунт (сек)
CHECK_EVERY = 24 * 3600
# Секції, у відповідях яких бувають фото викладачів
_RELEVANT = ("homework", "stat_marks", "stat_marks_year", "reviews")
# Ліміти завантаження: лише файли itstep.org і лише зображення до 3 МБ
_MAX_BYTES = 3 * 1024 * 1024
_ALLOWED_ROOT = "itstep.org"
_MAX_REDIRECTS = 3
# Дозволені типи (SVG свідомо немає: це активний контент) → розширення файлу
_EXT_BY_TYPE = {"image/jpeg": ".jpg", "image/png": ".png",
                "image/webp": ".webp", "image/gif": ".gif"}
ALLOWED_TYPES = frozenset(_EXT_BY_TYPE)

# Директор (контакти завжди показують його першим). Фото — з assets.
DIRECTOR = {
    "name": "Дмитро Корчевський",
    "role": "Ген. Директор",
    "photo_key": "director",
}
_DIRECTOR_FILE = BASE_DIR / "app" / "assets" / "contacts" / "director_korchevskyi.jpg"


@dataclass
class _Known:
    key: str            # public_key
    url: str            # source_url (посилання MyStat)
    teacher_id: int | None
    file_name: str
    content_type: str


# ---- оперативна пам'ять: усі відомі фото ----
# УВАГА: індекс — на ПРОЦЕС. При кількох воркерах кожен завантажує таблицю
# з БД у ensure_loaded(); фото, збережене іншим воркером, з'являється тут
# після промаху через запит до БД (file_for_key, _collect).
_lock = threading.Lock()
_loaded = False
_by_name: dict[tuple[str, str], _Known] = {}   # (філія, норм. ПІБ) → фото
_by_id: dict[tuple[str, int], _Known] = {}     # (філія, id викладача) → фото
_by_key: dict[str, _Known] = {}                # public_key → фото
_last_check: dict[tuple[int, str], float] = {}  # (account_id, секція) → monotonic
_inflight: set[tuple[str, str]] = set()        # (філія, ПІБ) у завантаженні
_pending: set[tuple[int, str]] = set()         # (account_id, секція) у роботі
_bg: set[asyncio.Task] = set()


# «School Горбенко Ксенія» (так у живих даних) і «Горбенко Ксенія School»
_SCHOOL_HEAD_RE = re.compile(r"^[(\[]?\s*school\s*[)\]]?[\s\-–—_|·,:.]+", re.IGNORECASE)
_SCHOOL_TAIL_RE = re.compile(r"[\s\-–—_|·,]+[(\[]?\s*school\s*[)\]]?\s*$", re.IGNORECASE)


def display_name(name: str | None) -> str:
    """ПІБ для ПОКАЗУ (Telegram-бот): без приписки «School». У БД і відповідях
    API ім'я лишається як є — звичайний і School-акаунт викладача різні."""
    s = (name or "").strip()
    return _SCHOOL_TAIL_RE.sub("", _SCHOOL_HEAD_RE.sub("", s)).strip() or s


def norm_name(name: str) -> str:
    """Ключ порівняння ПІБ: регістр і зайві пробіли не важливі."""
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def photos_dir() -> Path:
    p = Path(get_settings().teacher_photos_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _index(row: TeacherPhoto) -> None:
    k = _Known(row.public_key, row.source_url or "", row.teacher_id,
               row.file_name or "", row.content_type or "image/jpeg")
    _by_name[(row.branch_alias, norm_name(row.teacher_name))] = k
    _by_key[row.public_key] = k
    if row.teacher_id:
        _by_id[(row.branch_alias, int(row.teacher_id))] = k


def ensure_loaded() -> None:
    """Один раз підвантажити всю таблицю в пам'ять (синхронно, дешево)."""
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        db = SessionLocal()
        try:
            for row in db.query(TeacherPhoto).all():
                _index(row)
        finally:
            db.close()
        _loaded = True


# ------------------------------------------------------------ видача

def photo_path_for(branch: str, name: str, teacher_id: int | str | None = None) -> str | None:
    """Шлях до нашого фото викладача (/api/teacher-photos/<key>) або None.
    Спершу за id (надійніше), потім за ПІБ."""
    ensure_loaded()
    k: _Known | None = None
    try:
        tid = int(teacher_id) if teacher_id not in (None, "") else None
    except (TypeError, ValueError):
        tid = None
    if tid:
        k = _by_id.get((branch, tid))
    if k is None:
        k = _by_name.get((branch, norm_name(name)))
    if k is None or not k.file_name:
        return None
    return f"/api/teacher-photos/{k.key}"


def file_for_key(key: str) -> tuple[Path, str] | None:
    """public_key → (файл, content-type) для роутера. 'director' — з assets."""
    if key == DIRECTOR["photo_key"]:
        return (_DIRECTOR_FILE, "image/jpeg") if _DIRECTOR_FILE.exists() else None
    ensure_loaded()
    k = _by_key.get(key)
    if k is None:
        # промах: фото міг зберегти інший воркер — дивимось у БД
        k = _db_lookup_key(key)
    if k is None or not k.file_name:
        return None
    if k.content_type not in ALLOWED_TYPES:
        return None
    p = photos_dir() / k.file_name
    return (p, k.content_type) if p.exists() else None


def _db_lookup_key(key: str) -> _Known | None:
    """Запасний пошук за public_key у БД (і додавання в індекс)."""
    db = SessionLocal()
    try:
        row = db.query(TeacherPhoto).filter(TeacherPhoto.public_key == key).first()
        if row is None:
            return None
        with _lock:
            _index(row)
        return _by_key.get(key)
    finally:
        db.close()


def _find_row(db, branch: str, name: str) -> TeacherPhoto | None:
    """Рядок за (філія, НОРМАЛІЗОВАНИЙ ПІБ) — та сама нормалізація, що й в
    оперативному індексі (регістр і зайві пробіли не важливі)."""
    nn = norm_name(name)
    for row in db.query(TeacherPhoto).filter(TeacherPhoto.branch_alias == branch):
        if norm_name(row.teacher_name) == nn:
            return row
    return None


def _db_lookup_name(branch: str, name: str) -> _Known | None:
    """Запасний пошук за (філія, ПІБ) у БД (і додавання в індекс)."""
    db = SessionLocal()
    try:
        row = _find_row(db, branch, name)
        if row is None:
            return None
        with _lock:
            _index(row)
        return _by_name.get((branch, norm_name(name)))
    finally:
        db.close()


# ------------------------------------------------------------ збір

def _extract(obj, out: list[tuple[str, int | None, str]], depth: int = 0) -> None:
    """Обхід відповіді MyStat: усі (ПІБ, id|None, посилання на фото).
      • ДЗ / оцінки: dict з `fio_teach` → фото `teach_photo_pas` або `photo_pas`
        (у ДЗ `photo_pas` верхнього рівня — фото СТУДЕНТА, тому
        `teach_photo_pas` має пріоритет; студентські dict-и не мають fio_teach);
      • відгуки: dict з `teacher` + `teacher_photo`."""
    if depth > 8:
        return
    if isinstance(obj, list):
        for x in obj:
            _extract(x, out, depth + 1)
        return
    if not isinstance(obj, dict):
        return
    name = obj.get("fio_teach")
    if isinstance(name, str) and name.strip():
        url = obj.get("teach_photo_pas")
        if not url and "fio_stud" not in obj:
            url = obj.get("photo_pas")
        tid = obj.get("id_teach")
        try:
            tid = int(tid) if tid not in (None, "") else None
        except (TypeError, ValueError):
            tid = None
        if isinstance(url, str) and url.strip():
            out.append((name.strip(), tid, url.strip()))
    elif isinstance(obj.get("teacher"), str) and isinstance(obj.get("teacher_photo"), str):
        if obj["teacher"].strip() and obj["teacher_photo"].strip():
            out.append((obj["teacher"].strip(), None, obj["teacher_photo"].strip()))
    for v in obj.values():
        if isinstance(v, (dict, list)):
            _extract(v, out, depth + 1)


def _allowed(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host == _ALLOWED_ROOT or host.endswith("." + _ALLOWED_ROOT))


def _account_ctx(account_id: int) -> tuple[str, dict[str, int]] | None:
    """(філія, {норм. ПІБ → id_teach} з контактів) — у потоці."""
    db = SessionLocal()
    try:
        acc = db.get(MystatAccount, account_id)
        if acc is None:
            return None
        ids: dict[str, int] = {}
        row = (db.query(Snapshot)
               .filter(Snapshot.account_id == account_id,
                       Snapshot.section == "contacts").first())
        if row is not None:
            try:
                data = json.loads(row.payload) or {}
            except Exception:
                data = {}
            for t in data.get("teach_contacts") or []:
                if isinstance(t, dict) and t.get("fio_teach") and t.get("id_teach"):
                    try:
                        ids[norm_name(str(t["fio_teach"]))] = int(t["id_teach"])
                    except (TypeError, ValueError):
                        pass
        return acc.branch_alias or "", ids
    finally:
        db.close()


def _ext_for(ctype: str) -> str:
    return _EXT_BY_TYPE.get(ctype.split(";")[0].strip().lower(), ".jpg")


def _sniff(data: bytes) -> str | None:
    """Тип зображення за магічними байтами (None — не дозволений формат)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _save(branch: str, name: str, tid: int | None, url: str,
          data: bytes | None, ctype: str) -> None:
    """Upsert рядка + файл (у потоці). data=None — оновити лише id.

    Порядок: новий файл пишемо -> коміт БД -> лише потім видаляємо старий
    файл. При збої коміту новий файл прибираємо, старий лишається."""
    db = SessionLocal()
    new_path: Path | None = None
    old_name: str | None = None
    try:
        row = _find_row(db, branch, name)
        if row is None:
            row = TeacherPhoto(branch_alias=branch, teacher_name=name,
                               public_key=secrets.token_urlsafe(16))
            db.add(row)
        if tid:
            row.teacher_id = tid
        if data is not None:
            old_name = row.file_name
            fname = f"{secrets.token_hex(12)}{_ext_for(ctype)}"
            new_path = photos_dir() / fname
            new_path.write_bytes(data)
            row.file_name = fname
            row.content_type = ctype.split(";")[0].strip() or "image/jpeg"
            row.source_url = url
        row.updated_at = utcnow()
        try:
            db.commit()
        except Exception:
            db.rollback()
            if new_path is not None:
                try:
                    new_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        with _lock:
            _index(row)
        if old_name and new_path is not None and old_name != new_path.name:
            try:
                (photos_dir() / old_name).unlink(missing_ok=True)
            except OSError:
                pass
    finally:
        db.close()


async def _fetch(client: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    """Один GET без авто-редіректів. Повертає (байти, тип) або None;
    HTTPError піднімається (мережева помилка = збій, а не «немає фото»)."""
    async with client.stream("GET", url) as resp:
        if resp.status_code != 200:
            return None
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype not in ALLOWED_TYPES:
            return None
        cl = resp.headers.get("content-length")
        if cl and cl.isascii() and cl.isdigit() and int(cl) > _MAX_BYTES:
            return None
        buf = bytearray()
        async for chunk in resp.aiter_bytes():
            buf += chunk
            if len(buf) > _MAX_BYTES:
                return None
        data = bytes(buf)
    # магічні байти мають збігатися із заявленим типом
    if _sniff(data) != ctype:
        return None
    return data, ctype


async def _download(client: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    """Завантаження фото: редіректи вручну (до 3), кожен хоп - через
    _allowed() (https і *.itstep.org). Клієнт має follow_redirects=False."""
    cur = url
    for _ in range(_MAX_REDIRECTS + 1):
        if not _allowed(cur):
            return None
        async with client.stream("GET", cur) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    return None
                cur = str(httpx.URL(cur).join(loc))
                continue
        return await _fetch(client, cur)
    return None  # забагато редіректів


async def _collect(account_id: int, cands: list[tuple[str, int | None, str]]) -> bool:
    """True - перевірка завершилась без збоїв (можна тротлити на 24 год)."""
    await asyncio.to_thread(ensure_loaded)
    ctx = await asyncio.to_thread(_account_ctx, account_id)
    if ctx is None:
        return False
    branch, contact_ids = ctx
    if not branch:
        return False

    # швидке порівняння з пам'яттю: що нове / що змінилось
    todo: dict[str, tuple[int | None, str, bool]] = {}  # ПІБ -> (id, url, треба качати)
    for name, tid, url in cands:
        tid = tid or contact_ids.get(norm_name(name))
        k = _by_name.get((branch, norm_name(name)))
        if k is None:
            # промах RAM-індексу: можливо, фото вже зберіг інший воркер
            k = await asyncio.to_thread(_db_lookup_name, branch, name)
        if k is None or k.url != url or not k.file_name:
            if _allowed(url):
                todo[name] = (tid, url, True)
        elif tid and k.teacher_id != tid:
            todo.setdefault(name, (tid, url, False))
    if not todo:
        return True

    ok = True
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        for name, (tid, url, need_file) in todo.items():
            key = (branch, norm_name(name))
            if key in _inflight:
                continue
            _inflight.add(key)
            try:
                if need_file:
                    got = await _download(client, url)
                    if got is None:
                        continue
                    data, ctype = got
                    await asyncio.to_thread(_save, branch, name, tid, url, data, ctype)
                    _log.info("teacher photo saved: %s / %s", branch, name)
                else:
                    await asyncio.to_thread(_save, branch, name, tid, url, None, "")
            except Exception as exc:  # fail-soft: збір фото ніколи не ламає сайт
                ok = False
                _log.warning("teacher photo failed (%s): %r", name, exc)
            finally:
                _inflight.discard(key)
    return ok


async def _run(account_id: int, cands: list[tuple[str, int | None, str]],
               keys: list[tuple[int, str]]) -> None:
    """Виконує збір і ставить мітку тротлінгу ЛИШЕ після успіху."""
    try:
        done = await _collect(account_id, cands)
        if done:
            now = time.monotonic()
            for tk in keys:
                _last_check[tk] = now
    except Exception as exc:  # збій - не тротлимо на 24 год
        _log.warning("teacher photo check failed (acc=%s): %r", account_id, exc)
    finally:
        for tk in keys:
            _pending.discard(tk)


async def on_fresh_data(account_id: int, payloads: dict) -> None:
    """Слухач app_data.on_fresh_data: свіжі відповіді MyStat пройшли через нас.
    Сама перевірка - дешева (пам'ять); робота з мережею/БД - у фоні."""
    now = time.monotonic()
    rel = []
    keys: list[tuple[int, str]] = []
    for k, v in payloads.items():
        base = k.split("@", 1)[0]
        if base not in _RELEVANT:
            continue
        # раз на 24 год на акаунт для кожного типу відповіді: інакше перша
        # за добу відповідь ДЗ «з'їла» б перевірку оцінок (там інші викладачі)
        tk = (account_id, base)
        last = _last_check.get(tk)
        if last is not None and now - last < CHECK_EVERY:
            continue
        if tk in _pending:
            continue
        _pending.add(tk)   # мітка _last_check - лише після успіху (_run)
        keys.append(tk)
        rel.append(v)
    if not rel:
        return
    cands: list[tuple[str, int | None, str]] = []
    for p in rel:
        _extract(p, cands)
    if not cands:
        # фото у відповідях немає - перевірка завершена
        for tk in keys:
            _last_check[tk] = now
            _pending.discard(tk)
        return
    # унікальні за (ПІБ, url): відповідь ДЗ повторює викладача десятки разів
    uniq = list({(n, u): (n, t, u) for n, t, u in cands}.values())
    t = asyncio.create_task(_run(account_id, uniq, keys))
    _bg.add(t)
    t.add_done_callback(_bg.discard)
