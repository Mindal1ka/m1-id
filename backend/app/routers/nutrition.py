"""Роутер харчування (FoodStep): меню, замовлення, налаштування, автозамовлення."""
from __future__ import annotations

import json
import logging
from datetime import date as _date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.responses import ApiError, ok
from app.deps import get_db
from app.db.models import FoodstepConfig, FoodstepOrder, FoodstepVariation, \
    User
from app.deps import get_current_user
from app.core.config import get_settings
from app.services import foodstep as fs
from app.services.ratelimit import rate_limit

_log = logging.getLogger("m1id.nutrition")

async def _require_pl(db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)) -> None:
    """FoodStep — лише для філії pl: без pl-акаунта усі ендпоінти віддають 403."""
    if not fs.user_has_pl(db, user.id):
        raise ApiError(403, "foodstep_branch_unsupported")


router = APIRouter(prefix="/api/nutrition", tags=["nutrition"],
                   dependencies=[Depends(_require_pl)])


def _is_admin(user: User) -> bool:
    """Адмін: user_id == 1 або M1ID_ADMIN_IDS (та сама логіка, що в plugins)."""
    ids = {1}
    for part in (getattr(get_settings(), "admin_user_ids", "") or "").split(","):
        part = part.strip()
        if (part.isascii() and part.isdigit()):
            ids.add(int(part))
    return user.id in ids


def _require_password(cfg: FoodstepConfig) -> str:
    pwd = fs.foodstep_password(cfg)
    if not pwd:
        raise ApiError(400, "foodstep_password_not_set")
    return pwd


# ---------------------------------------------------------------- меню


@router.get("/menu", dependencies=[rate_limit(30, 60)])
async def menu(supplier: str = Query(default="dumpling"),
               force: bool = Query(default=False),
               user: User = Depends(get_current_user)) -> dict:
    """Меню постачальника (кеш на бекенді + HTTP-кеш 2 год у браузера).
    force (обхід кешу) — лише для адмінів; для решти параметр ігнорується."""
    from fastapi.responses import JSONResponse
    force = force and _is_admin(user)
    try:
        data = await fs.get_menu(supplier, force=force)
    except ValueError as exc:
        raise ApiError(502, str(exc)) from exc
    except Exception as exc:  # мережа/редизайн сайту
        raise ApiError(502, "foodstep_unavailable") from exc
    return JSONResponse(
        content=ok(data),
        headers={"Cache-Control": "private, max-age=7200"},
    )


@router.get("/suppliers", dependencies=[rate_limit(60, 60)])
async def suppliers(user: User = Depends(get_current_user)) -> dict:
    return ok(fs.SUPPLIERS)


@router.get("/img", dependencies=[rate_limit(300, 60)])
async def img(src: str = Query(description="/content/assets/dishes/…"),
              user: User = Depends(get_current_user)):
    """Проксі картинок FoodStep (той самий WAF-набір заголовків)."""
    from fastapi.responses import Response
    if not src.startswith("/content/") or ".." in src or len(src) > 300:
        raise ApiError(400, "bad_src")
    try:
        data, ctype = await fs.fetch_image(src)
    except Exception as exc:
        raise ApiError(502, "image_unavailable") from exc
    return Response(data, media_type=ctype,
                    headers={"Cache-Control": "private, max-age=86400",
                             "X-Content-Type-Options": "nosniff"})


# ---------------------------------------------------------------- конфіг


@router.get("/config")
async def get_config(db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> dict:
    cfg = fs.get_config(db, user.id)
    return ok({**fs.config_view(cfg),
               "variations": fs.variations_view(db, user.id)})


class ConfigIn(BaseModel):
    supplier: str | None = None
    auto_enabled: bool | None = None
    auto_mode: str | None = None
    fixed_variation_id: int | None = None
    order_time: str | None = None  # "HH:MM"
    notify_minutes: int | None = Field(default=None, ge=0, le=720)
    allow_weekends: bool | None = None
    skip_dates: list[str] | None = None


@router.put("/config")
async def put_config(body: ConfigIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> dict:
    cfg = fs.get_config(db, user.id)
    if body.supplier is not None:
        if body.supplier not in fs._SUPPLIER_TITLES:
            raise ApiError(400, "unknown_supplier")
        cfg.supplier = body.supplier
    if body.auto_enabled is not None:
        cfg.auto_enabled = body.auto_enabled
    if body.auto_mode is not None:
        if body.auto_mode not in ("random", "fixed"):
            raise ApiError(400, "bad_mode")
        cfg.auto_mode = body.auto_mode
    if body.fixed_variation_id is not None:
        cfg.fixed_variation_id = body.fixed_variation_id
    if body.order_time is not None:
        parts = body.order_time.split(":")
        if len(parts) != 2 or not all((p.isascii() and p.isdigit()) for p in parts):
            raise ApiError(400, "bad_time")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ApiError(400, "bad_time")
        # автозамовлення — не пізніше 8:00 (дедлайн FoodStep 9:00)
        if h > 8 or (h == 8 and m > 0):
            raise ApiError(400, "too_late")
        cfg.order_time = f"{h:02d}:{m:02d}"
    if body.notify_minutes is not None:
        cfg.notify_minutes = body.notify_minutes
    if body.allow_weekends is not None:
        cfg.allow_weekends = body.allow_weekends
    if body.skip_dates is not None:
        cfg.skip_dates = json.dumps(body.skip_dates)
    db.commit()
    return ok(fs.config_view(cfg))


class PasswordIn(BaseModel):
    password: str = Field(min_length=4, max_length=64)


@router.post("/password")
async def set_password(body: PasswordIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)) -> dict:
    """Пароль FoodStep. Зберігаємо зашифровано (Fernet, як токени MyStat);
    у відповіді — лише маска. Перевіряємо живим запитом меню? Ні —
    пароль потрібен тільки при замовленні, тому просто зберігаємо."""
    from app.core.security import encrypt_secret
    cfg = fs.get_config(db, user.id)
    cfg.password_enc = encrypt_secret(body.password)
    db.commit()
    return ok({"password_set": True, "mask": "•" * len(body.password)})


# ---------------------------------------------------------------- варіації


class VariationIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    items: list[dict] = Field(min_length=1)
    supplier: str = Field(default="", max_length=32)


@router.get("/variations")
async def get_variations(db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)) -> dict:
    return ok(fs.variations_view(db, user.id))


@router.post("/variations")
async def post_variation(body: VariationIn, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)) -> dict:
    items = [{"id": int(i["id"]), "count": max(1, int(i.get("count") or 1))}
             for i in body.items]
    cfg = fs.get_config(db, user.id)
    supplier = body.supplier if body.supplier in ("dumpling", "provinces") \
        else cfg.supplier
    row = FoodstepVariation(user_id=user.id, name=body.name.strip(),
                            supplier=supplier,
                            items_json=json.dumps(items, ensure_ascii=False))
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok({"id": row.id, "name": row.name, "supplier": supplier,
               "items": items})


@router.delete("/variations/{vid}")
async def del_variation(vid: int, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)) -> dict:
    row = db.query(FoodstepVariation).filter_by(id=vid, user_id=user.id).first()
    if row is None:
        raise ApiError(404, "not_found")
    db.delete(row)
    db.commit()
    return ok({"deleted": True})


# ---------------------------------------------------------------- замовлення


class OrderIn(BaseModel):
    supplier: str | None = None
    dates: list[str] = Field(min_length=1, max_length=31)
    items: list[dict] = Field(min_length=1)


@router.post("/order")
async def order(body: OrderIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> dict:
    """Замовлення на НЕСКІЛЬКИ дат одним викликом: по одному /ajax/addorder
    на кожну дату. Уже замовлені дати пропускаються (already)."""
    cfg = fs.get_config(db, user.id)
    supplier = body.supplier or cfg.supplier
    if supplier not in fs._SUPPLIER_TITLES:
        raise ApiError(400, "unknown_supplier")
    pwd = _require_password(cfg)
    items = [{"id": int(i["id"]), "count": max(1, int(i.get("count") or 1))}
             for i in body.items]

    results = []
    for d in body.dates[:31]:
        try:
            _date.fromisoformat(d)
        except ValueError as exc:
            raise ApiError(400, f"bad_date_{d}") from exc
        if fs.has_order(db, user.id, d):
            results.append({"date": d, "status": "already", "ok": False})
            continue
        try:
            res = await fs.place_order(pwd, supplier, d, items)
        except ValueError as exc:
            results.append({"date": d, "ok": False, "status": "Error",
                            "message": str(exc)})
            continue
        except Exception as exc:
            results.append({"date": d, "ok": False, "status": "Error",
                            "message": "network_error"})
            _log.warning("foodstep order %s %s: %r", user.id, d, exc)
            continue
        status = "ok" if res["ok"] else "failed"
        _, created = fs.record_order(db, user.id, d, supplier, items,
                                     res["total"], "manual", status)
        results.append({"date": d, "ok": res["ok"] and created,
                        "status": res["status"],
                        "message": res["message"],
                        "total": res["total"]})
    return ok({"results": results})


@router.delete("/order")
async def cancel_order(date: str = Query(description="YYYY-MM-DD"),
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)) -> dict:
    """Скасування замовлення на майбутню дату:
    1) POST /ajax/delorder на FoodStep (може не підтримуватись — тоді
    статус Unknown);
    2) у будь-якому разі позначаємо запис журналу як cancelled, щоб
    автозамовлення знову не замовило цю дату, а календар показав сіру
    позначку. Вже минулі дати скасувати не можна."""
    from app.core.clock import naive_kyiv_now
    try:
        _date.fromisoformat(date)
    except ValueError as exc:
        raise ApiError(400, "bad_date") from exc
    if date < naive_kyiv_now().date().isoformat():
        raise ApiError(400, "past_date")
    cfg = fs.get_config(db, user.id)
    pwd = _require_password(cfg)
    row = (db.query(FoodstepOrder)
           .filter_by(user_id=user.id, order_date=date, status="ok")
           .first())
    if row is None:
        raise ApiError(404, "not_found")
    try:
        res = await fs.cancel_order(pwd, row.supplier, date)
    except Exception:
        res = {"ok": False, "status": "Unknown", "message": "network_error",
               "password_failure": False}
    if res.get("password_failure"):
        raise ApiError(401, "foodstep_bad_password")
    row.status = "cancelled"
    db.commit()
    return ok({"cancelled": True, "remote": res.get("ok", False),
               "remote_status": res.get("status", "Unknown"),
               "note": ("FoodStep підтвердив скасування."
                        if res.get("ok") else
                        "FoodStep не підтвердив скасування — дата позначена "
                        "скасованою локально, перевір на foodstep.online.")})


@router.get("/orders")
async def orders(limit: int = Query(default=60, ge=1, le=200),
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> dict:
    return ok({"orders": fs.orders_view(db, user.id, limit)})


@router.get("/calendar")
async def calendar(month: str = Query(description="YYYY-MM"),
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> dict:
    """Мапа ordered-дат місяця для календаря."""
    try:
        y, m = (int(x) for x in month.split("-"))
        first = _date(y, m, 1)
    except (ValueError, TypeError) as exc:
        raise ApiError(400, "bad_month") from exc
    last = (_date(y + m // 12, m % 12 + 1, 1) if m < 12 else _date(y + 1, 1, 1))
    from datetime import timedelta
    end = last - timedelta(days=1)
    return ok({"ordered": fs.ordered_dates(db, user.id, first, end),
               "cancelled": fs.cancelled_dates(db, user.id, first, end)})