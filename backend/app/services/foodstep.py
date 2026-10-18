"""FoodStep (foodstep.online) — їдальня Полтавської філії.

Джерело даних: реверс-інжиніринг за TECHNICAL_SPEC.md (§3.3, §4.1, §7):
- меню — серверний HTML /main/alldinners?supplier={slug}, парсимо регуляркою;
- замовлення — POST /ajax/addorder (form-urlencoded), одне замовлення
  на дату, пароль передається відкритим текстом (тому він завжди йде
  з бекенду, з зашифрованого сховища, ніколи з фронту/бота).
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.db.models import FoodstepConfig, FoodstepOrder, FoodstepVariation, \
    MystatAccount

_log = logging.getLogger("m1id.foodstep")

SUPPLIERS = [
    {"slug": "dumpling", "title": "Полтавські Галушки"},
    {"slug": "provinces", "title": "Провінція"},
]
_SUPPLIER_TITLES = {s["slug"]: s["title"] for s in SUPPLIERS}

# ---------------------------------------------------------------- клієнт

_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=30,
            # False: на POST із паролем редірект міг би переслати його далі
            follow_redirects=False,
            headers={
                # повний браузерний набір: foodstep.online (Hostinger WAF)
                # віддає 403, якщо немає Sec-Fetch-* / Accept-* / Referer
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/126.0.0.0 Safari/537.36"),
                "Accept": ("text/html,application/xhtml+xml,application/xml;"
                           "q=0.9,image/avif,image/webp,*/*;q=0.8"),
                "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
                "Referer": get_settings().foodstep_base_url + "/main/checksupplier",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Upgrade-Insecure-Requests": "1",
            },
        )
    return _client


# ---------------------------------------------------------------- меню

# кеш меню в пам'яті: {supplier: (monotonic_ts, data)}
_menu_cache: dict[str, tuple[float, dict]] = {}

_RE_WEIGHT = re.compile(r'(\d+)\s*гр')
_RE_CATEGORY = re.compile(r'<h2 class="text-center">(.*?)</h2>')

# --- поблочний парсинг: кожну страву ріжемо окремо, щоб збій
# розмітки в одній картці не «з'їдав» сусідні (старий ланцюг .*?
# знаходив лише ~половину страв) ---
_RE_DISH_ID = re.compile(r'dishes_id">(\d+)</p>')
_RE_COREX = re.compile(r'corex_id">(\d*)</p>')
_RE_IMG = re.compile(r'<img[^>]*src="([^"]+)"')
_RE_TITLE = re.compile(r'product_title"><a[^>]*>(.*?)</a>', re.S)
_RE_PRICE_LI = re.compile(r'class="(?:new|old)_price">(.*?)</li>', re.S)
_RE_PRICE = re.compile(r'product-price">\s*([\d.]+)')


def _parse_menu(html: str, supplier: str) -> dict:
    """HTML меню → {categories: [{name, dishes:[{id,title,price,weight,…}]}]}.

    Порційно: блок = текст від чергового dishes_id до наступного.
    У картці буває old_price з описом салату (ігноруємо для ваги) і
    new_price виду «300 гр - <span class=product-price>62</span> грн.»
    (варіанти ваги: «150/50», «1 шт», «3 штуки», «0.5 л» або порожньо)."""
    cats = [(m.start(), _html.unescape(m.group(1)).strip())
            for m in _RE_CATEGORY.finditer(html)]
    categories: list[dict] = [{"name": "", "dishes": []}]
    markers = list(_RE_DISH_ID.finditer(html))
    for i, m in enumerate(markers):
        block = html[m.start():markers[i + 1].start()
                     if i + 1 < len(markers) else len(html)]
        corex_m = _RE_COREX.search(block)
        corex = corex_m.group(1) if corex_m else ""
        img_m = _RE_IMG.search(block)
        title_m = _RE_TITLE.search(block)
        if title_m is None:
            continue  # не картка страви — пропускаємо
        pos = m.start()
        name = ""
        if cats:
            prev = [c for p, c in cats if p < pos]
            name = prev[-1] if prev else ""
        if not name and corex:
            name = _COREX.get(int(corex), "")
        # new_price (зважування + ціна); якщо порожній — дивимось old_price
        price = 0
        weight = ""
        for li in _RE_PRICE_LI.findall(block):
            pm = _RE_PRICE.search(li)
            if pm is None:
                continue
            price = int(float(pm.group(1).replace(",", ".")))
            w = li[:pm.start()].split('<')[0].strip().rstrip('-').strip()
            w = _html.unescape(w).strip()
            if w:
                weight = w
            break
        if not categories or categories[-1]["name"] != name:
            categories.append({"name": name, "dishes": []})
        categories[-1]["dishes"].append({
            "id": int(m.group(1)),
            "title": _html.unescape(title_m.group(1)).strip(),
            "price": price,
            "weight": weight,
            "image": img_m.group(1) if img_m and
                img_m.group(1).startswith("/") else None,
            "corex_id": int(corex) if corex else None,
        })
    return {
        "supplier": supplier,
        "supplier_title": _SUPPLIER_TITLES.get(supplier, supplier),
        "categories": [c for c in categories if c["dishes"]],
        "dishes": [d for c in categories for d in c["dishes"]],
    }


# категорії за corex_id (spec §3.2)
_COREX = {48: "Перші страви", 47: "Другі страви / М'ясо та гарніри"}


async def get_menu(supplier: str, force: bool = False) -> dict:
    """Меню постачальника з кешем (TTL settings.foodstep_menu_ttl_minutes)."""
    supplier = supplier if supplier in _SUPPLIER_TITLES else "dumpling"
    ttl = max(300, get_settings().foodstep_menu_ttl_minutes * 60)
    if not force and supplier in _menu_cache:
        ts, data = _menu_cache[supplier]
        if time.monotonic() - ts < ttl:
            return data
    url = f"{get_settings().foodstep_base_url.rstrip('/')}/main/alldinners?supplier={supplier}"
    resp = await _http().get(url, follow_redirects=True)  # GET без секретів
    resp.raise_for_status()
    data = _parse_menu(resp.text, supplier)
    if not data["dishes"]:
        raise ValueError("foodstep_menu_empty")
    _menu_cache[supplier] = (time.monotonic(), data)
    return data


# LRU-кеш картинок: обмежений за кількістю й сумарним розміром
_IMG_CACHE_MAX_ITEMS = 300
_IMG_CACHE_MAX_BYTES = 40 * 1024 * 1024
_IMG_MAX_ONE = 2 * 1024 * 1024
_img_cache: "OrderedDict[str, tuple[bytes, str]]" = OrderedDict()
_img_cache_bytes = 0


async def fetch_image(src: str) -> tuple[bytes, str]:
    """Картинка страви з foodstep.online (дозволені тільки /content/)."""
    if not src.startswith("/content/") or ".." in src:
        raise ValueError("bad_src")
    global _img_cache_bytes
    cached = _img_cache.get(src)
    if cached:
        _img_cache.move_to_end(src)
        return cached
    url = get_settings().foodstep_base_url.rstrip("/") + src
    resp = await _http().get(url, follow_redirects=True)
    resp.raise_for_status()
    ctype = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    if not ctype.startswith("image/") or ctype == "image/svg+xml":
        raise ValueError("bad_image_type")
    data = resp.content
    if len(data) > _IMG_MAX_ONE:
        return data, ctype  # завеликі в кеш не кладемо
    prev = _img_cache.pop(src, None)
    if prev is not None:
        _img_cache_bytes -= len(prev[0])
    _img_cache[src] = (data, ctype)
    _img_cache_bytes += len(data)
    while _img_cache and (len(_img_cache) > _IMG_CACHE_MAX_ITEMS
                          or _img_cache_bytes > _IMG_CACHE_MAX_BYTES):
        _, (old, _ct) = _img_cache.popitem(last=False)
        _img_cache_bytes -= len(old)
    return data, ctype


# ---------------------------------------------------------------- пароль


def foodstep_password(cfg: FoodstepConfig) -> str:
    if not cfg.password_enc:
        return ""
    return decrypt_secret(cfg.password_enc)


# ---------------------------------------------------------------- замовлення


async def place_order(password: str, supplier: str, order_date: str,
                      items: list[dict]) -> dict:
    """POST /ajax/addorder. items = [{id, count}] — title/price бек
    підставляє сам з кешованого меню (не довіряємо клієнту, spec §6.3)."""
    menu = await get_menu(supplier)
    by_id = {d["id"]: d for d in menu["dishes"]}
    form: list[tuple[str, str]] = [
        ("password", password),
        ("dateOrder", order_date),
        ("supplier", supplier),
    ]
    total = 0
    n = 0
    for it in items:
        dish = by_id.get(int(it["id"]))
        if dish is None:
            raise ValueError(f"unknown_dish_{it['id']}")
        count = max(1, int(it.get("count") or 1))
        form.append((f"order[{n}][id]", str(dish["id"])))
        form.append((f"order[{n}][title]", dish["title"]))
        form.append((f"order[{n}][price]", str(dish["price"])))
        form.append((f"order[{n}][count]", str(count)))
        total += dish["price"] * count
        n += 1
    if n == 0:
        raise ValueError("empty_order")

    import urllib.parse
    url = (f"{get_settings().foodstep_base_url.rstrip('/')}/ajax/addorder")
    body = urllib.parse.urlencode(form)
    resp = await _http().post(url, content=body,
                              headers={"Content-Type":
                                       "application/x-www-form-urlencoded"})
    try:
        data = resp.json()
    except Exception:
        data = {"status": "Error", "message": f"HTTP {resp.status_code}"}
    status = str(data.get("status") or "")
    ok = "Success" in status
    return {
        "ok": ok,
        "status": status or "Error",
        "message": str(data.get("message") or ""),
        "total": total,
        "password_failure": "Failure" in status,
    }


async def cancel_order(password: str, supplier: str, order_date: str) -> dict:
    """POST /ajax/delorder — скасування замовлення на дату.
    FoodStep може не повернути JSON (порожня відповідь) — тоді
    статус Unknown, і скасування фіксуємо лише локально."""
    import urllib.parse
    url = (f"{get_settings().foodstep_base_url.rstrip('/')}/ajax/delorder")
    body = urllib.parse.urlencode([
        ("password", password),
        ("dateOrder", order_date),
        ("supplier", supplier),
    ])
    resp = await _http().post(url, content=body,
                              headers={"Content-Type":
                                       "application/x-www-form-urlencoded"})
    try:
        data = resp.json()
    except Exception:
        data = {"status": "Unknown", "message": f"HTTP {resp.status_code}"}
    status = str(data.get("status") or "Unknown")
    return {
        "ok": "Success" in status,
        "status": status,
        "message": str(data.get("message") or ""),
        "password_failure": "Failure" in status,
    }


# ---------------------------------------------------------------- журнал


def _dish_map(supplier: str | None) -> dict[int, dict]:
    """Мапа id → страва з кеша меню (пріоритет — меню постачальника)."""
    out: dict[int, dict] = {}
    for sup in _SUPPLIER_TITLES:
        if supplier and sup != supplier and sup in _menu_cache:
            continue
        if sup in _menu_cache:
            for d in _menu_cache[sup][1]["dishes"]:
                out.setdefault(d["id"], d)
    return out


def _enrich_items(items: list[dict], supplier: str | None) -> list[dict]:
    """Додаємо title/price до items перед записом у журнал, щоб
    замість «#10×1» показувати людські назви на сайті та в боті."""
    names = _dish_map(supplier)
    out = []
    for it in items:
        d = names.get(int(it["id"]))
        out.append({
            "id": int(it["id"]),
            "count": int(it.get("count") or 1),
            "title": (d or {}).get("title") or it.get("title"),
            "price": (d or {}).get("price") if d else it.get("price", 0),
        })
    return out


def _order_view(row: FoodstepOrder) -> dict:
    return {
        "date": row.order_date,
        "supplier": row.supplier,
        "supplier_title": _SUPPLIER_TITLES.get(row.supplier, row.supplier),
        "items": json.loads(row.items_json or "[]"),
        "total": row.total,
        "source": row.source,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def orders_view(db: Session, user_id: int, limit: int = 60) -> list[dict]:
    rows = (db.query(FoodstepOrder)
            .filter(FoodstepOrder.user_id == user_id)
            .order_by(FoodstepOrder.order_date.desc())
            .limit(max(1, min(limit, 200))).all())
    return [_order_view(r) for r in rows]


def ordered_dates(db: Session, user_id: int,
                  from_d: date, to_d: date) -> dict[str, dict]:
    """Мапа date → {total, supplier} для календаря."""
    rows = (db.query(FoodstepOrder)
            .filter(FoodstepOrder.user_id == user_id,
                    FoodstepOrder.order_date >= from_d.isoformat(),
                    FoodstepOrder.order_date <= to_d.isoformat(),
                    FoodstepOrder.status == "ok")
            .all())
    return {r.order_date: {"total": r.total, "supplier": r.supplier} for r in rows}


def cancelled_dates(db: Session, user_id: int,
                    from_d: date, to_d: date) -> dict[str, dict]:
    """Скасовані дати (для сірих позначок у календарі)."""
    rows = (db.query(FoodstepOrder)
            .filter(FoodstepOrder.user_id == user_id,
                    FoodstepOrder.order_date >= from_d.isoformat(),
                    FoodstepOrder.order_date <= to_d.isoformat(),
                    FoodstepOrder.status == "cancelled")
            .all())
    return {r.order_date: {"total": r.total, "supplier": r.supplier} for r in rows}


def has_order(db: Session, user_id: int, order_date: str) -> bool:
    return db.query(FoodstepOrder.id).filter_by(
        user_id=user_id, order_date=order_date, status="ok").first() is not None


def record_order(db: Session, user_id: int, order_date: str, supplier: str,
                 items: list[dict], total: int, source: str, status: str
                 ) -> tuple[FoodstepOrder, bool]:
    """Запис у журнал. False = на цю дату вже є успішне замовлення."""
    if status == "ok" and has_order(db, user_id, order_date):
        return db.query(FoodstepOrder).filter_by(
            user_id=user_id, order_date=order_date, status="ok").first(), False
    row = db.query(FoodstepOrder).filter_by(
        user_id=user_id, order_date=order_date).first()
    items = _enrich_items(items, supplier)
    if row is None:
        row = FoodstepOrder(user_id=user_id, order_date=order_date)
        db.add(row)
    row.supplier = supplier
    row.items_json = json.dumps(items, ensure_ascii=False)
    row.total = total
    row.source = source
    row.status = status
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.query(FoodstepOrder).filter_by(
            user_id=user_id, order_date=order_date, status="ok").first(), False
    db.refresh(row)
    return row, True


# ---------------------------------------------------------------- конфіг


# FoodStep обслуговує лише школу IT STEP у Полтаві: код філії MyStat «pl».
FOODSTEP_BRANCH = "pl"


def user_has_pl(db: Session, user_id: int) -> bool:
    """Чи є в користувача M1 ID хоч один підключений акаунт філії pl.
    Без такого акаунта харчування недоступне (сайт, бот, автозамовлення)."""
    rows = (db.query(MystatAccount.branch_alias)
            .filter(MystatAccount.user_id == user_id)
            .filter(MystatAccount.status != "disabled").all())
    return any((r[0] or "").strip().lower() == FOODSTEP_BRANCH for r in rows)


def get_config(db: Session, user_id: int) -> FoodstepConfig:
    cfg = db.query(FoodstepConfig).filter_by(user_id=user_id).first()
    if cfg is None:
        cfg = FoodstepConfig(user_id=user_id)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def config_view(cfg: FoodstepConfig) -> dict:
    return {
        "supplier": cfg.supplier,
        "password_set": bool(cfg.password_enc),
        "auto": {
            "enabled": cfg.auto_enabled,
            "mode": cfg.auto_mode,
            "fixed_variation_id": cfg.fixed_variation_id,
            "order_time": cfg.order_time,
            "notify_minutes": cfg.notify_minutes,
            "allow_weekends": cfg.allow_weekends,
            "skip_dates": json.loads(cfg.skip_dates or "[]"),
        },
    }


def variations_view(db: Session, user_id: int) -> list[dict]:
    rows = (db.query(FoodstepVariation)
            .filter(FoodstepVariation.user_id == user_id)
            .order_by(FoodstepVariation.id).all())
    return [{"id": r.id, "name": r.name,
             "supplier": r.supplier or "dumpling",
             "items": json.loads(r.items_json or "[]")} for r in rows]


def items_human(items: list[dict]) -> str:
    """«Борщ ×1, Компот ×2 — 92 грн» для TG/сайту: спершу назва,
    збережена в журналі, потім — з кеша меню."""
    names: dict[int, dict] = {}
    for sup in _SUPPLIER_TITLES:
        if sup in _menu_cache:
            for d in _menu_cache[sup][1]["dishes"]:
                names[d["id"]] = d
    parts: list[str] = []
    total = 0
    for it in items:
        d = names.get(int(it["id"]))
        count = int(it.get("count") or 1)
        title = it.get("title") or (d["title"] if d else f"#{it['id']}")
        price = int(it.get("price") or (d["price"] if d else 0))
        parts.append(f"{title} ×{count}")
        total += price * count
    return ", ".join(parts) + (f" — {total} грн" if total else "")


def default_target_date(now: date | datetime | None = None) -> date:
    """Дата за замовчуванням: до 9:00 (за Києвом) — сьогодні, після — завтра.
    ЗАВЖДИ повертає date (не datetime!): від цього залежать ключі
    дедупу планувальника (fired_marks) і записи в skip_dates."""
    from datetime import datetime as _dt

    from app.core.clock import naive_kyiv_now
    n = now or naive_kyiv_now()
    if isinstance(n, _dt):
        base, hour = n.date(), n.hour
    else:
        base, hour = n, naive_kyiv_now().hour
    return base if hour < 9 else base + timedelta(days=1)


def next_days(count: int = 14, now: date | None = None) -> list[date]:
    d0 = default_target_date(now)
    return [d0 + timedelta(days=i) for i in range(count)]