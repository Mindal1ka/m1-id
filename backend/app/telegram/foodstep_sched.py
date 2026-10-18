"""Планувальник автозамовлення FoodStep.

Живе поруч із poller у процесі API (asyncio-таск зі runtime.py):
- за cfg.notify_minutes до order_time — TG-попередження з ВИБРАНОЮ
  варіацією і кнопкою «Відмінити»;
- о order_time — саме замовлення: вибір варіації (рандом/фіксована,
  або та, що користувач обрав у попередженні), записи в журнал.
Мітки «вже повідомлено/виконано» на добу — в пам'яті (зникають
за рестарт — тоді просто спрацюють повторно лише на наступний цикл).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, time as _time, timedelta

from app.db.base import SessionLocal
from app.db.models import FoodstepConfig, FoodstepOrder, TelegramLink
from app.core.clock import naive_kyiv_now
from app.services import foodstep as fs
from app.telegram import bot as tg
from app.telegram import foodstep_bot as fsb

_log = logging.getLogger("m1id.foodstep.sched")

# «Пропустити» на добу — у cfg.skip_dates (БД); мітки notify/exec —
# теж у БД (cfg.fired_marks), щоб рестарт процесу не спамив знову.
_skips: set[str] = set()      # "uid:date" — додатково, у пам'яті процесу


def _cfg_date_key(cfg: FoodstepConfig) -> str:
    return f"{cfg.user_id}:{naive_kyiv_now().date().isoformat()}"


def _marks(cfg: FoodstepConfig) -> dict:
    try:
        return dict(json.loads(cfg.fired_marks or "{}"))
    except Exception:
        return {}


def _save_marks(db, cfg: FoodstepConfig, marks: dict, iso: str) -> None:
    # зберігаємо і чистимо старі доби (лиш key з поточною датою)
    cfg.fired_marks = json.dumps(
        {k: v for k, v in marks.items() if iso in k})
    db.commit()


def _pick_variation(db, cfg: FoodstepConfig) -> dict | None:
    """Варіація на сьогодні: фіксована (якщо режим fixed), інакше рандом."""
    variants = fs.variations_view(db, cfg.user_id)
    if not variants:
        return None
    if cfg.auto_mode == "fixed":
        for v in variants:
            if v["id"] == cfg.fixed_variation_id:
                return v
    return random.choice(variants)


def _skip_dates(cfg: FoodstepConfig) -> set[str]:
    try:
        return set(json.loads(cfg.skip_dates or "[]"))
    except Exception:
        return set()


async def _run_tick() -> None:
    now = naive_kyiv_now()
    # чистимо мітки «пропустити» за минулі доби — інакше множина росте вічно
    today_iso = now.date().isoformat()
    for k in [k for k in _skips if k.rsplit(":", 1)[-1] < today_iso]:
        _skips.discard(k)
    db = SessionLocal()
    try:
        configs = db.query(FoodstepConfig).filter_by(auto_enabled=True).all()
        for cfg in configs:
            try:
                # FoodStep лише для філії pl: інших не обробляємо взагалі
                if not fs.user_has_pl(db, cfg.user_id):
                    continue
                await _process(db, cfg, now)
            except Exception as exc:
                _log.warning("autoorder uid=%s: %r", cfg.user_id, exc)
    finally:
        db.close()


async def _process(db, cfg: FoodstepConfig, now: datetime) -> None:
    chat_id = _chat_of(db, cfg.user_id)
    # цільова дата замовлення: до 9:00 — сьогодні, після — завтра
    # (дедлайн FoodStep 9:00). Саме на цю дату рахуємо і попередження,
    # і виконання — тому попередження за N хв працює і через північ
    # (наприклад, 570 хв до завтрашніх 8:00 → сповіщення ввечері).
    target = fs.default_target_date(now)
    iso = target.isoformat()
    if target == now.date() and now.strftime("%H:%M") >= "09:00":
        return  # вікно на сьогодні закрилось (страховка)
    # вихідні — не замовляємо (у школи немає уроків, FoodStep не приймає):
    # якщо колись знадобиться — поле allow_weekends лишилось у конфігу
    if target.weekday() >= 5 and not cfg.allow_weekends:
        return
    if iso in _skip_dates(cfg):
        return
    if fs.has_order(db, cfg.user_id, iso):
        return  # уже замовлено (вручну або автозамовленням)
    if cfg.password_enc == "":
        return
    # немає TG — попередити ніде, але замовлення все одно виконуємо нижче
    h, m = (int(x) for x in cfg.order_time.split(":"))
    order_at = datetime.combine(target, _time(h, m))

    # --- попередження за N хвилинами ---
    marks = _marks(cfg)
    nkey = f"{cfg.user_id}:{iso}:notify"
    vkey = f"{cfg.user_id}:{iso}:var"
    warn_at = order_at - timedelta(minutes=cfg.notify_minutes)
    if now >= warn_at and now < order_at and not marks.get(nkey):
        marks[nkey] = 1
        variant = _pick_variation(db, cfg)
        if variant:  # запам'ятовуємо, щоб замовити САМЕ показану варіацію
            marks[vkey] = variant["id"]
        _save_marks(db, cfg, marks, iso)
        if chat_id:
            await fsb.send_autoorder_warning(
                chat_id, cfg.user_id, variant, order_at,
                variant["supplier"] if variant else cfg.supplier)

    # --- виконання ---
    ekey = f"{cfg.user_id}:{iso}:exec"
    if now >= order_at and not marks.get(ekey):
        marks[ekey] = 1
        _save_marks(db, cfg, marks, iso)
        # користувач натиснув «Відмінити»? (skip живе в cfg.skip_dates / _skips)
        if f"{cfg.user_id}:{iso}" in _skips:
            if chat_id:
                await tg.send_text(chat_id, "⛔️ Автозамовлення сьогодні пропущено.",
                                   tg.notify_kb())
            return
        # «пізніше 8:00» — не замовляємо (дедлайн FoodStep 9:00)
        if now.hour > 8 or (now.hour == 8 and now.minute > 0):
            if chat_id:
                await tg.send_text(
                    chat_id, "⛔️ Автозамовлення пропущено — час уже пізніше 8:00.",
                    tg.notify_kb())
            return
        variant = None
        if marks.get(vkey):  # та, що була в попередженні
            variant = next((v for v in fs.variations_view(db, cfg.user_id)
                            if v["id"] == marks[vkey]), None)
        if variant is None:
            variant = _pick_variation(db, cfg)
        if variant is None:
            if chat_id:
                await tg.send_text(
                    chat_id, "⚠️ Автозамовлення: немає жодної варіації. "
                             "Створи на сайті у вкладці «Харчування».",
                    tg.notify_kb())
            return
        pwd = fs.foodstep_password(cfg)
        if not pwd:
            return
        try:
            res = await fs.place_order(pwd, variant["supplier"], iso, variant["items"])
        except Exception as exc:
            _log.warning("autoorder exec uid=%s: %r", cfg.user_id, exc)
            res = {"ok": False, "status": "Error", "message": "network_error",
                   "total": 0}
        status = "ok" if res["ok"] else "failed"
        fs.record_order(db, cfg.user_id, iso, variant["supplier"],
                        variant["items"], res["total"], "auto", status)
        if chat_id:
            if res["ok"]:
                await tg.send_text(
                    chat_id,
                    f"🤖 <b>Автозамовлення виконано</b> ({_fmt_d(iso)})\n"
                    f"✅ {tg._esc(fs.items_human(variant['items']))}",
                    tg.foodstep_cancel_kb(iso))
            else:
                await tg.send_text(
                    chat_id,
                    f"⚠️ <b>Автозамовлення не вдалося</b> ({_fmt_d(iso)})\n"
                    f"{tg._esc(res.get('message') or res.get('status') or '')}\n"
                    "Встигни замовити вручну до 9:00.",
                    tg.foodstep_error_kb())


def _fmt_d(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso).date()
    except ValueError:
        return iso
    return d.strftime("%d.%m")


def _chat_of(db, user_id: int) -> int | None:
    link = db.query(TelegramLink).filter_by(user_id=user_id).first()
    return link.chat_id if link else None


# ---------------------------------------------------------------- нове меню

async def run_scheduler() -> None:
    """Хвилинний цикл. Ніколи не падає назавжди."""
    while True:
        try:
            await _run_tick()
        except Exception as exc:
            _log.error("scheduler tick failed: %r", exc)
        # спимо до початку наступної хвилини
        now = naive_kyiv_now()
        await asyncio.sleep(60 - now.second + 0.5)
