"""Наше агреговане API даних (M3).

Принципи (рішення користувача):
  • усі запити до mapi — асинхронні (httpx.AsyncClient, gather);
  • фронт отримує ГОТОВІ дані в НАШОМУ форматі одним викликом,
    а не сирі відповіді MyStat по 10 разів;
  • джерело — снапшоти (миттєво), протухлі секції дотягуються
    з mapi паралельно й оновлюють кеш.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import threading
import zipfile
from urllib.parse import quote

import httpx
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.core.clock import naive_kyiv_now
from app.core.config import get_settings
from app.core.responses import ApiError
from app.core.security import decrypt_secret
from app.db.base import SessionLocal
from app.db.models import MystatAccount, Snapshot
from app.services import mystat_client as ms
from app.services.branch_names import branch_display_name
from app.services.sync_engine import Task, build_plan
from app.services.sync_engine import CLUBS_ENABLED  # noqa: F401

# TTL кешу за секціями (секунди): як часто можна ходити в живий API
TTL = {
    "profile": 3600,
    "config": 86_400,
    "counters": 120,
    "balances": 300,
    "schedule_week": 600,
    "schedule_month": 3_600,
    "homework": 300,
    "stat_marks": 900,
    "stat_marks_year": 600,
    "news": 300,
    "shop_products": 900,
    "shop_orders": 120,
    "qr": 86_400,
    "leader_points": 300,
    "leader_table": 300,
    # M5: платежі / клуби / контакти
    "payment_info": 3_600,
    "payment_next": 3_600,
    "payment_history": 3_600,
    "payment_schedule": 3_600,
    "clubs": 3_600,
    "club_abonements": 3_600,
    "club_balance": 3_600,
    "club_transactions": 3_600,
    "contacts": 86_400,
    # Нагороди (аватар за бобрів) + прогрес по місяцях.
    # Нагороди — 5 хв (баланс/наявність змінюється після покупок),
    # прогрес — 30 хв: місячна гранулярність, частіше не має сенсу.
    "awards_items": 300,
    "awards_balance": 300,
    "stat_progress": 1_800,
}
_DEFAULT_TTL = 900
# оновлюємо токен MyStat заздалегідь, до спливання (див. get_payloads/проксі)
_PROACTIVE_MARGIN = timedelta(seconds=120)


# ------------------------------------------------- «свіжі дані з mapi»
# Хук для єдиного життя бота і сайту: КОЛИ ЗАВГОДНО хтось (сайт, сокет,
# poller, команда бота) витягнув свіжі дані з mapi — усі підписники
# діють на це негайно. Telegram-poller підписується в main.py і на
# кожній свіжій порції проганяє детекти змін → сповіщення приходять
# в той самий момент, коли користувач побачив нові дані на сайті, а
# не тільки на черговому 30-хвилинному циклі.
_fresh_listeners: list = []
_fresh_bg: set[asyncio.Task] = set()


def on_fresh_data(fn) -> None:
    """Підписка: fn(account_id, payloads: dict[str, dict]) — coroutine.
    Викликається ПІСЛЯ успішного збереження свіжих payload'ів у снапшоти."""
    if fn not in _fresh_listeners:
        _fresh_listeners.append(fn)


async def _safe_listener(coro) -> None:
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # слухач ніколи не ламає викликача
        import logging as _log

        _log.getLogger("m1id.tg").warning(
            "fresh-data listener failed: %r", exc)


def _emit_fresh(account_id: int, payloads: dict[str, dict]) -> None:
    """Розсилка свіжих даних підписникам (fire-and-forget задачі)."""
    if not _fresh_listeners or not payloads:
        return
    for fn in _fresh_listeners:
        try:
            coro = fn(account_id, dict(payloads))
        except Exception:
            continue
        if coro is not None and asyncio.iscoroutine(coro):
            t = asyncio.create_task(_safe_listener(coro))
            _fresh_bg.add(t)
            t.add_done_callback(_fresh_bg.discard)


def _utcnow_naive() -> datetime:
    """Наївний UTC (SQLite не зберігає tzinfo) без deprecation-warning."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _kyiv_today() -> date:
    """«Сьогодні» за київським часом (а не за зоною сервера)."""
    return naive_kyiv_now().date()


def _ttl(section: str) -> int:
    return TTL.get(section, _DEFAULT_TTL)


_WEEK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_date_filter(kind: str, arg: str) -> str:
    """Сувора перевірка date_filter: week → YYYY-MM-DD (реальна дата),
    month → YYYY-MM. Інакше 422 (довільний рядок потрапив би в query mapi)."""
    ok_fmt = False
    if kind == "week":
        if _WEEK_RE.fullmatch(arg):
            try:
                date.fromisoformat(arg)
                ok_fmt = True
            except ValueError:
                pass
    else:
        ok_fmt = bool(_MONTH_RE.fullmatch(arg))
    if not ok_fmt:
        raise ApiError(422, "bad_date", "date",
                       "week_must_be_YYYY-MM-DD_month_must_be_YYYY-MM")
    return arg


def task_for(section: str, branch_alias: str = "pl") -> Task | None:
    """section → задача зі специ. Підтримує параметризовані секції:
    schedule_week@YYYY-MM-DD (будь-яка дата → тиждень Пн–Нд, перевірено live),
    schedule_month@YYYY-MM."""
    base = section.split("@", 1)[0]
    alias = branch_alias or "pl"  # гілка береться з профілю акаунта
    if "@" in section and base.startswith("schedule_"):
        _, _, arg = section.partition("@")
        kind = "week" if base == "schedule_week" else "month"
        arg = _validate_date_filter(kind, arg)
        # alias іде в ШЛЯХ, arg — у query: кодуємо обидва (захист від ін'єкції)
        path = (f"/v1/mystat/{quote(alias, safe='')}/schedule/get-month"
                f"?type={kind}&date_filter={quote(arg, safe='')}")
        return Task(base, path, "Розклад", method="GET")
    return {t.section: t for t in build_plan(alias)}.get(base)


def _mapi_unreachable(exc: Exception) -> ApiError:
    """Мережева/транспортна помилка httpx → чесний 502 замість 500."""
    return ApiError(502, "mystat_unavailable", "__all__",
                    f"mystat_unreachable_{type(exc).__name__}")


def ttl_for(section: str) -> int:
    base = section.split("@", 1)[0]
    return TTL.get(section, TTL.get(base, _DEFAULT_TTL))


# ---------------------------------------------------------------- завантаження


async def get_payloads(db, account: MystatAccount,
                       sections: list[str], force: bool = False,
                       pacer: "object | None" = None) -> dict[str, dict]:
    """→ {section: payload}. Свіжі — зі снапшотів, прострочені — паралельно з mapi.

    pacer — опціональний services.mapi_pacer.RequestPacer (фоновий цикл
    poller'а, режим «по запитах»): кожен mapi-виклик займає власний слот,
    запити рівномірно розмазуються по вікну. None = без pacування
    (інтерактивні виклики сайту/сокета)."""
    result: dict[str, dict] = {}
    stale: list[str] = []

    now = _utcnow_naive()
    for section in sections:
        row = (db.query(Snapshot)
               .filter(Snapshot.account_id == account.id,
                       Snapshot.section == section)
               .first())
        if row is not None:
            # fetched_at зберігається наївним UTC — порівнюємо з наївним UTC,
            # інакше timestamp() трактує його як локальний час (TZ-баг)
            fresh = row.fetched_at is not None and (
                now - row.fetched_at).total_seconds() < ttl_for(section)
            if fresh and not force:
                try:
                    import json as _json

                    result[section] = _json.loads(row.payload)
                    continue
                except Exception:
                    pass
        stale.append(section)

    if stale:
        # account може бути DETACHED: бот/поллер/дейлі передають інстанс,
        # отриманий з УЖЕ ЗАКРИТОЇ сесії (Session.close() → detach).
        # Тоді ms.set_account_token(account, ...) + db.commit() зберігали
        # НІЧОГО — ORM-об'єкт не належить цій сесії, і оновлення
        # токена/needs_relogin мовчки втрачалося (нескінченні повторні
        # refresh і «мертва» сесія для сайту). Перепідключаємо за PK.
        alive = (db.query(MystatAccount.id)
                 .filter(MystatAccount.id == account.id).first())
        if alive is None:
            raise ApiError(404, "account_not_found", "__all__",
                           "account_deleted")
        account = db.merge(account)
        # Серіалізуємо мутації акаунта (token/статус + commit): секції
        # летять паралельно в gather по ОДНІЙ сесії; guard не тримається
        # через await (критична секція синхронна), тому він безпечний.
        _write_guard = threading.Lock()
        try:
            token = decrypt_secret(account.access_token_enc)
        except ValueError:
            account.status = "needs_relogin"
            db.commit()
            raise ApiError(401, "account_needs_relogin", "__all__",
                           "token_unreadable_after_restart_re_link_account")
        language = account.language or "uk"

        def _call(tok: str, task: Task):
            return ms.request_async(
                task.method, task.path, token=tok, language=language,
                user_id=account.id_user_storage or None)

        # проактивний refresh: якщо токен ось-ось мине (або минув),
        # оновлюємо ДО запиту — не витрачаємо 401-раундтрип на кожну секцію.
        # best-effort: транзитний збій mapi (таймаут/503) не має
        # валити запит у 500 — нижче є 401-ланцюжок і stale-фолббек.
        exp = account.token_expires_at
        if exp is not None and exp <= _utcnow_naive() + _PROACTIVE_MARGIN:
            try:
                new_tok = await ms.refresh_once(
                    token, language, user_id=account.id_user_storage or None)
            except ms.MystatError as _exc:
                import logging as _log

                _log.getLogger("m1id").warning(
                    "mapi_call_fail proactive_refresh %r — йдемо зі старим "
                    "токеном (ланцюжок 401 підстрахує)", _exc)
            else:
                if new_tok:
                    with _write_guard:
                        ms.set_account_token(account, new_tok)
                        db.commit()
                    token = new_tok

        dead_session = {"flag": False}

        async def fetch_one(section: str):
            # DEMO SCHEDULE HOOK: тиждень 24–30.08.2026 віддається з
            # services/demo_schedule.py. Видалення демо = видалити файл:
            # ImportError нижче автоматично вимикає хук.
            try:
                from .demo_schedule import demo_payload
            except ImportError:  # демо видалено — хук мовчить
                demo_payload = None
            if demo_payload is not None and not get_settings().demo_schedule:
                # прапорець M1ID_DEMO_SCHEDULE не увімкнено — фейкові дані
                # ніколи не потрапляють до клієнтів (prod-дефолт)
                demo_payload = None
            if demo_payload is not None:
                dp = demo_payload(section)
                if dp is not None:
                    return section, dp
            task = task_for(section, account.branch_alias)
            if task is None:
                return section, None
            tok = token
            try:
                # Pacер (режим «по запитах»): тільки ПЕРША спроба —
                # повтор після 401/refresh не чекає нового слота (щоб
                # не видовжувати 401-ланцюжок).
                if pacer is not None:
                    await pacer.slot()
                resp = await _call(tok, task)
                if resp.status_code == 401:
                    # 401 → один спільний refresh (single-flight) → повтор
                    new_tok = await ms.refresh_once(
                        tok, language,
                        user_id=account.id_user_storage or None)
                    if new_tok:
                        with _write_guard:
                            ms.set_account_token(account, new_tok)
                            db.commit()
                        tok = new_tok
                        resp = await _call(tok, task)
                if resp.status_code == 200:
                    return section, resp.json()
                if resp.status_code == 401:
                    # refresh не врятував токен — чесно підіймаємо прапорець,
                    # інакше фронт показав би порожні розділи як «немає даних»
                    dead_session["flag"] = True
                    with _write_guard:
                        account.status = "needs_relogin"
                        db.commit()
                else:
                    # 5xx/429/403 від mapi: видно в логах (пошук «mapi_call_fail»)
                    import logging as _log

                    _log.getLogger("m1id").warning(
                        "mapi_call_fail %s %s -> %s (віддаємо stale-снапшот)",
                        task.method, task.path, resp.status_code)
            except Exception as _exc:
                import logging as _log

                _log.getLogger("m1id").warning(
                    "mapi_call_fail %s %s -> %r (віддаємо stale-снапшот)",
                    task.method, task.path, _exc)
            # mapi недоступний / помилка / таймаут — віддаємо СТАРИЙ снапшот:
            # користувач бачить останні валідні дані замість «пусто»
            # (секція просто не оновилася). Порожнечу показуємо лише якщо
            # снапшота ніколи не було.
            try:
                old = (db.query(Snapshot)
                       .filter(Snapshot.account_id == account.id,
                               Snapshot.section == section)
                       .first())
                if old is not None:
                    import json as _json
                    return section, _json.loads(old.payload)
            except Exception:
                pass
            return section, None

        fetched = await asyncio.gather(*(fetch_one(s) for s in stale))
        if dead_session["flag"]:
            raise ApiError(401, "account_needs_relogin", "__all__",
                           "refresh_failed_re_enter_credentials")

        for section, payload in fetched:
            if payload is not None:
                result[section] = payload
                _save_snapshot(db, account.id, section, payload)

        # свіжі дані щойно з mapi → повідомити підписників (Telegram-poller
        # проганяє детекти: сповіщення одночасно з тим, що побачив сайт)
        fresh = {s: p for s, p in fetched if p is not None}
        if fresh:
            _emit_fresh(account.id, fresh)

    return result


def _save_snapshot(db, account_id: int, section: str, payload: Any) -> None:
    import json as _json

    from sqlalchemy.exc import IntegrityError

    raw = _json.dumps(payload, ensure_ascii=False)
    for _attempt in range(2):
        # SELECT-then-INSERT переганяється з паралельним синком (інший воркер /
        # thread-fallback): обидва не знаходять рядок → UNIQUE(account_id,
        # section) → IntegrityError. Повтор після rollback працює як
        # UPDATE по вже вставленому конкурентом рядку.
        row = (db.query(Snapshot)
               .filter(Snapshot.account_id == account_id,
                       Snapshot.section == section)
               .first())
        if row is None:
            db.add(Snapshot(account_id=account_id, section=section, payload=raw))
        else:
            row.payload = raw
            row.fetched_at = _utcnow_naive()
        try:
            db.commit()
            return
        except IntegrityError:
            db.rollback()  # паралельний INSERT виграв гонку — повторимо


# ================================================================ ФОРМАТ M1

HW_STATUS_LABEL = {3: "до виконання", 2: "на перевірці", 1: "виконано",
                   5: "ретейк"}


async def delete_submission(db, account: MystatAccount, homework_id: int) -> dict:
    """Видалити здану роботу (статус «на перевірці»).
    Живий контракт з rollback-скриптів: DELETE /homework/delete/{id ЗДАЧІ}
    → 200 true; id здачі = homework_stud.id у картці."""
    card = await homework_card(db, account, homework_id)  # 404/502 всередині
    sid = ((card.get("homework_stud") or {}).get("id"))
    if not sid:
        raise ApiError(409, "hw_nothing_to_delete", "__all__", "no_submission")

    try:
        token = decrypt_secret(account.access_token_enc)
    except ValueError:
        account.status = "needs_relogin"
        db.commit()
        raise ApiError(401, "account_needs_relogin", "__all__",
                       "token_unreadable_after_restart_re_link_account")

    language = account.language or "uk"
    uid = account.id_user_storage or None

    async def _del(tok: str):
        try:
            return await ms.request_async(
                "DELETE",
                f"/v1/mystat/{account.branch_alias}/homework/delete/{sid}",
                token=tok, language=language, user_id=uid)
        except httpx.HTTPError as exc:
            raise _mapi_unreachable(exc) from exc

    r = await _del(token)
    if r.status_code == 401:
        try:
            new_tok = await ms.refresh_once(token, language, user_id=uid)
        except ms.MystatError as exc:
            raise ApiError(502, "mystat_unavailable", "__all__",
                           "mystat_temporarily_unreachable_during_refresh") from exc
        if new_tok:
            ms.set_account_token(account, new_tok)
            db.commit()
            r = await _del(new_tok)
        else:
            account.status = "needs_relogin"
            db.commit()
            raise ApiError(401, "account_needs_relogin", "__all__",
                           "refresh_failed_re_enter_credentials")
    if r.status_code == 401:
        account.status = "needs_relogin"
        db.commit()
        raise ApiError(401, "account_needs_relogin", "__all__",
                       "mystat_session_rejected_re_enter_credentials")
    if r.status_code != 200:
        raise ApiError(502, "mystat_unavailable", "__all__",
                       f"hw_delete_status_{r.status_code}")
    # M1-посилання цієї ДЗ більше не мають сенсу — вилучаємо
    try:
        from app.services import links as _links
        _links.deactivate_homework(account.user_id, homework_id)
    except Exception:
        pass
    return {"deleted": True, "submission_id": sid}


def _file_links(raw: Any) -> list[str]:
    """mapi віддає посилання на файли через кому (probe_submit*.py)."""
    if not isinstance(raw, str) or not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


async def homework_card(db, account: MystatAccount, homework_id: int) -> dict:
    """Повна картка ДЗ: живий запит /homework/{id} → {"0": {...}}.
    Форму знято diag_hw_card2.py на реальному акаунті."""
    try:
        token = decrypt_secret(account.access_token_enc)
    except ValueError:
        account.status = "needs_relogin"
        db.commit()
        raise ApiError(401, "account_needs_relogin", "__all__",
                       "token_unreadable_after_restart_re_link_account")

    language = account.language or "uk"
    uid = account.id_user_storage or None

    async def _get(tok: str):
        try:
            return await ms.request_async(
                "GET",
                f"/v1/mystat/{account.branch_alias}/homework/{homework_id}",
                token=tok, language=language, user_id=uid)
        except httpx.HTTPError as exc:
            raise _mapi_unreachable(exc) from exc

    r = await _get(token)
    if r.status_code == 401:
        # ланцюжок як у проксі: refresh → повторити
        try:
            new_tok = await ms.refresh_once(token, language, user_id=uid)
        except ms.MystatError as exc:
            # транзитна аварія mapi — не «сесія померла», чесний 502
            raise ApiError(502, "mystat_unavailable", "__all__",
                           "mystat_temporarily_unreachable_during_refresh") from exc
        if new_tok:
            ms.set_account_token(account, new_tok)
            db.commit()
            r = await _get(new_tok)
        else:
            account.status = "needs_relogin"
            db.commit()
            raise ApiError(401, "account_needs_relogin", "__all__",
                           "refresh_failed_re_enter_credentials")
    if r.status_code == 401:
        # свіжий токен усе одно отримав 401 — сесія справді мертва
        account.status = "needs_relogin"
        db.commit()
        raise ApiError(401, "account_needs_relogin", "__all__",
                       "mystat_session_rejected_re_enter_credentials")
    if r.status_code != 200:
        raise ApiError(502, "mystat_unavailable", "__all__",
                       f"homework_card_status_{r.status_code}")
    try:
        payload = r.json()
    except Exception:
        payload = None
    card = payload.get("0") if isinstance(payload, dict) else None
    if not isinstance(card, dict):
        raise ApiError(404, "hw_not_found", "__all__", "homework_card_missing")
    return card


LATE_PENALTY_COINS = 20      # ціна здачі «архівного» ДЗ (як у офіційному клієнті)
LATE_PENALTY_DAYS = 183      # дедлайн раніше за стільки днів → платна здача
RETAKE_COST_COINS = 2        # ціна запиту на перездачу виконаного ДЗ


def _late_penalty(due_raw: Any, unlock_expire: Any,
                  limit_days: Any = None, coins: Any = None) -> int:
    """Штраф за здачу ДЗ із давно минулим дедлайном — правило офіційного
    клієнта (chunk D06T): `diff(дедлайн, зараз, днів) < -182`, не відкрито
    перездачу і `homework_stud.unlock_expire !== "1"` → кнопка «Надіслати −20».
    Параметри віддає сам mapi у кожному ДЗ (перевірено live): ліміт днів —
    `default_deadline_days` (182), ціна — `coins_to_close_deadline` (20);
    за їх відсутності діють константи. Рахуємо за ДЕДЛАЙНОМ (overdue_time),
    а не за датою створення."""
    if str(unlock_expire) == "1" or not due_raw:
        return 0
    try:
        d_due = date.fromisoformat(str(due_raw)[:10])
    except ValueError:
        return 0
    try:
        days = int(limit_days) + 1 if limit_days not in (None, "") else LATE_PENALTY_DAYS
    except (TypeError, ValueError):
        days = LATE_PENALTY_DAYS
    try:
        cost = int(coins) if coins not in (None, "") else LATE_PENALTY_COINS
    except (TypeError, ValueError):
        cost = LATE_PENALTY_COINS
    return cost if (_kyiv_today() - d_due).days >= days else 0


def _autotest_kind(x: dict) -> str:
    """`is_autotest` у mapi: 0 — звичайне ДЗ, 2 — ЕСЕ (перевірено live: усі
    есе мають 2 і відповідь текстом у homework_stud.stud_answer), інше
    ненульове — автотест (значень ≠ 0/2 в живих даних ще не бачили ⚠️)."""
    raw = str(x.get("is_autotest") if x.get("is_autotest") is not None else 0)
    if raw in ("", "0", "False", "false"):
        return "homework"
    return "essay" if raw == "2" else "test"


def _hw_kind(x: dict) -> str:
    """Англомовний ключ типу ДЗ (як у офіційному клієнті, getTypeLabel):
    essay | test | independent_work (ospr 0) | practice_work (ospr 1).
    Невідомий ospr → `type_<ospr>`: фронт покаже ключ як є (англійською)."""
    kind = _autotest_kind(x)
    if kind in ("essay", "test"):
        return kind
    raw = str(x.get("ospr") if x.get("ospr") is not None else 0).strip()
    return {"0": "independent_work", "1": "practice_work"}.get(raw, f"type_{raw}")


def homework_card_view(c: dict) -> dict:
    """Сира картка mapi → наш чистий формат для модалки деталей."""
    stud = c.get("homework_stud") or {}
    hwc = c.get("homework_comment") or {}
    st = c.get("status")
    if st in (5, 6):  # прострочене — як «до виконання» (як і в списку), здавати можна
        st = 3
    history = [
        {"type": h.get("type_name"), "text": h.get("comment"),
         "date": h.get("date"), "file": h.get("file")}
        for h in (stud.get("communication_history") or [])
        if isinstance(h, dict)
    ]
    # «Моя відповідь» — лише ОСТАННЯ здача: mapi накопичує старі
    # файли в file_path через кому, тому беремо файли з найсвіжішого
    # запису communication_history (фолбек — сам file_path)
    hist_files = [h for h in history if h.get("file")]
    if hist_files:
        answer_files = _file_links(hist_files[-1]["file"])
    else:
        answer_files = _file_links(stud.get("file_path"))
    return {
        "id": c.get("id"),
        "subject": c.get("name_spec") or "",
        "title": c.get("theme") or "",
        "teacher": c.get("fio_teach") or "",
        "teach_photo": c.get("teach_photo_pas") or None,
        "status": st,
        "status_label": HW_STATUS_LABEL.get(st, "?"),
        "assigned": c.get("creation_time") or None,
        "due": c.get("overdue_time") or None,
        "completed": c.get("completion_time") or None,
        "description": c.get("comment") or "",
        "attachment": c.get("file_path") or None,
        "mark": stud.get("mark"),
        "answer_text": stud.get("stud_answer") or "",
        "answer_files": answer_files,
        "submitted_at": stud.get("creation_time") or None,
        "submission_id": stud.get("id"),
        "coins": c.get("coins_to_close_deadline"),
        # ціна здачі: −20 для давно простроченого, −2 за перездачу виконаного
        "late_penalty": (_late_penalty(c.get("overdue_time"),
                                       stud.get("unlock_expire"),
                                       c.get("default_deadline_days"),
                                       c.get("coins_to_close_deadline"))
                         if st == 3 else 0),
        "retake_cost": RETAKE_COST_COINS,
        "kind": _hw_kind(c),
        "is_test": _autotest_kind(c) == "test",
        "is_essay": _autotest_kind(c) == "essay",
        "autotest_status": c.get("autotest_status"),
        "autotest_result": c.get("autotest_result"),
        "teacher_comment": hwc.get("text_comment") or "",
        "history": [
            {"type": h.get("type_name"), "text": h.get("comment"),
             "date": h.get("date"), "file": h.get("file")}
            for h in (stud.get("communication_history") or [])
            if isinstance(h, dict)
        ],
    }


def norm_homework(x: dict, group_status: int | None = None) -> dict:
    """Жива форма: /homework/list → [{status, data: [item]}, ...],
    параметри status/limit/type[] сервер ігнорує (перевірено live)."""
    stud = x.get("homework_stud") or {}
    status = x.get("status") if x.get("status") is not None else group_status
    cdays = x.get("completion_days")
    overdue = max(0, -cdays) if isinstance(cdays, (int, float)) else 0
    # Прострочені лишаються «до виконання»: офіційний клієнт дає
    # здавати їх (перевірено користувачем на #103819), бере лише
    # штраф −20 монет. Тому серверне «6» переводимо назад у 3,
    # а спізнення показуємо червоним чипом за датою дедлайну.
    # Ретейк (5) теж окремої категорії не має — це «до виконання»
    # з бейджем is_retake.
    if status in (5, 6):
        status = 3
    due_raw = x.get("overdue_time") or None
    late_penalty = 0
    if status == 3 and due_raw:
        try:
            d_due = date.fromisoformat(str(due_raw)[:10])
            if d_due < _kyiv_today():
                overdue = max(overdue, (_kyiv_today() - d_due).days)
        except ValueError:
            pass
        late_penalty = _late_penalty(
            due_raw, stud.get("unlock_expire"),
            x.get("default_deadline_days"), x.get("coins_to_close_deadline"))
    # здані роботи (на перевірці / виконано) простроченими бути не можуть —
    # вони здані; «прострочено» чесно лише для «до виконання» і ретейка
    if status in (1, 2):
        overdue = 0
    return {
        "id": x.get("id"),
        "subject": x.get("name_spec") or "",
        "title": x.get("theme") or "",
        "teacher": x.get("fio_teach") or "",
        "assigned": x.get("creation_time") or None,
        "due": due_raw,
        "status": status,
        "status_label": HW_STATUS_LABEL.get(status, "?"),
        "mark": stud.get("mark"),
        "attachment": bool(x.get("file_path")),
        "answer": bool(stud.get("file_path") or stud.get("stud_answer")),
        "kind": _hw_kind(x),
        "is_test": _autotest_kind(x) == "test",
        "is_essay": _autotest_kind(x) == "essay",
        "is_retake": str(stud.get("is_retake")) == "1",
        "overdue_days": int(overdue),
        "late_penalty": int(late_penalty),
        "retake_cost": RETAKE_COST_COINS,
    }


def homework_view(payloads: dict[str, Any]) -> dict:
    raw = payloads.get("homework")
    groups = raw if isinstance(raw, list) else []
    items: list[dict] = []
    for grp in groups:
        if not isinstance(grp, dict):
            continue
        st = grp.get("status")
        for x in grp.get("data") or []:
            if isinstance(x, dict):
                items.append(norm_homework(x, st))

    # «гарячі» зверху: pending → retake → checking → done, всередині — за дедлайном
    order = {3: 0, 5: 1, 2: 2, 1: 3}
    items.sort(key=lambda h: (order.get(h["status"], 4),
                              h["due"] or "9999-12-31"))

    counts = {"pending": 0, "checking": 0, "done": 0}
    key_by_status = {3: "pending", 2: "checking", 1: "done"}
    for h in items:
        g = key_by_status.get(h["status"])
        if g:
            counts[g] += 1

    subjects = sorted({h["subject"] for h in items if h["subject"]})
    # ВСІ незакриті з дедлайном (віджет Головної листає всередині),
    # порядок уже за зростанням due, бо items сортовані pending->...->done
    nearest = [h for h in items if h["status"] == 3 and h["due"]]
    return {"items": items, "counts": counts, "subjects": subjects,
            "total": len(items), "nearest_deadlines": nearest}


def _norm_activity(i: dict) -> dict:
    lesson = i.get("lesson_name")
    name = i.get("name") or ""
    return {
        "id": i.get("id"),
        "date": str(i.get("created_at", ""))[:10],
        "title": lesson or name,
        "subtitle": name if lesson else "",
        "mark": i.get("mark"),
        "icon": i.get("icon"),
        "awards": [
            {"alias": a.get("award_alias"), "value": a.get("award_value", 0)}
            for a in (i.get("awards") or [])
            if a.get("award_value")
        ],
    }


async def activity_page(db, account, page: int = 1,
                        per_page: int = 20) -> dict:
    """progress/activity (new_format=1) з ланцюжком refresh і пагінацією."""
    try:
        token = decrypt_secret(account.access_token_enc)
    except ValueError:
        account.status = "needs_relogin"
        db.commit()
        raise ApiError(401, "account_needs_relogin", "__all__",
                       "token_unreadable_after_restart_re_link_account")

    language = account.language or "uk"
    path = (f"/v1/mystat/{account.branch_alias}/progress/activity"
            f"?new_format=1&per_page={per_page}&page={page}")

    resp = None
    for _attempt in (1, 2):
        try:
            resp = await ms.request_async(
                "GET", path, token=token, language=language,
                user_id=account.id_user_storage or None)
        except httpx.HTTPError as exc:
            raise _mapi_unreachable(exc) from exc
        if resp.status_code != 401:
            break
        try:
            new_token = await ms.refresh_once(
                token, language, user_id=account.id_user_storage or None)
        except ms.MystatError as exc:
            # транзієнтна аварія апстрима — не «сесія померла», 502 (не 500)
            raise ApiError(502, "mystat_unavailable", "__all__",
                           "mystat_temporarily_unreachable_during_refresh") from exc
        if new_token is None:
            account.status = "needs_relogin"
            db.commit()
            raise ApiError(401, "account_needs_relogin", "__all__",
                           "refresh_failed_re_enter_credentials")
        token = new_token
        ms.set_account_token(account, new_token)
        db.commit()

    if resp.status_code == 401:
        # свіжий токен відхилено — сесія справді мертва (не 502)
        account.status = "needs_relogin"
        db.commit()
        raise ApiError(401, "account_needs_relogin", "__all__",
                       "mystat_session_rejected_re_enter_credentials")
    if resp.status_code != 200:
        raise ApiError(502, "mystat_unavailable", "__all__",
                       f"activity_status_{resp.status_code}")

    try:
        raw = resp.json()
    except Exception:
        raw = []
    items = [_norm_activity(i) for i in (raw if isinstance(raw, list) else [])
             if isinstance(i, dict)]

    def _h(key: str) -> int:
        try:
            return int(resp.headers.get(key, 0))
        except (TypeError, ValueError):
            return 0

    total_pages = _h("x-pagination-page-count") or 1
    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total_count": _h("x-pagination-total-count"),
        "has_more": page < total_pages,
    }


def balances_view(payloads: dict[str, Any]) -> dict:
    bal = payloads.get("balances")
    counters = payloads.get("counters")
    items = []
    if isinstance(bal, list):
        icon = {"cristals": "💎", "coins": "🪙", "achivements": "🏅"}
        for b in bal:
            items.append({
                "key": b.get("alias") or "?",
                "icon": icon.get(b.get("alias"), "⭐"),
                "value": b.get("value", 0),
                "rating": b.get("rating"),
            })
    ctr: dict[str, int] = {}
    if isinstance(counters, list):
        for c in counters:
            ctr[c.get("counter_type", "?")] = c.get("counter", 0)
    return {"items": items, "unread_counters": ctr}


def schedule_view(payloads: dict[str, Any], section: str) -> dict:
    """schedule/get-month → {range, days:[{date, weekday, lessons:[…]}]}.
    section — ключ секції цілком: schedule_week | schedule_month | …@дата."""
    payload = payloads.get(section)
    kind = "month" if "month" in section.split("@", 1)[0] else "week"
    lessons: list[dict] = []
    meta: dict = {}
    if isinstance(payload, dict):
        meta = {k: payload.get(k) for k in
                ("start_day", "end_date", "first_visit_day", "last_visit_day")}
        raw = payload.get("data")
        if isinstance(raw, list):
            # захист від «денного» формату: деякі гілки/фільтри mapi можуть
            # віддати data як [{date, lessons: [...]}, ...] (контейнери днів),
            # а не плоский список пар. Раніше кожен день ставав ОДНИМ
            # фантомним уроком (пустий предмет/час) → віджет «Сьогодні»
            # показував одну криву стрічку замість усіх пар. Тут
            # розгортаємо контейнери назад у плоский список.
            flat: list[dict] = []
            for it in raw:
                if not isinstance(it, dict):
                    continue
                inner = it.get("lessons")
                if isinstance(inner, list):
                    for l in inner:
                        if isinstance(l, dict):
                            row = dict(l)
                            row.setdefault("date", it.get("date") or "")
                            if "week_day" not in row:
                                row["week_day"] = it.get("week_day")
                            flat.append(row)
                else:
                    flat.append(it)
            lessons = [norm_lesson(l) for l in flat]
    elif isinstance(payload, list):  # на випадок голого масиву
        lessons = [norm_lesson(l) for l in payload if isinstance(l, dict)]

    days: dict[str, dict] = {}
    # Сортування ЗА ЧАСОМ (не lesson_no): MyStat шле пари в довільному
    # порядку, а lesson_no має діри (2,3,5,8,11) і навіть дублікати -
    # хронологія старту єдина стабільна опція. Стабільний порядок = стабільні
    # хеші в poller'і (без фальшивих «розклад змінився»).
    for l in sorted(lessons, key=lambda x: (x["date"], x["start"],
                                            x["end"], x["lesson_no"])):
        day = days.setdefault(l["date"],
                              {"date": l["date"], "weekday": l.get("weekday"),
                               "lessons": []})
        day["lessons"].append(l)
    return {
        "kind": kind,
        "section": section,
        "range": meta,
        "days": sorted(days.values(), key=lambda d: d["date"]),
        "total_lessons": len(lessons),
    }


_WEEKDAYS_UK = ["", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]


def _split_special_mark(raw: Any) -> tuple[Any, bool]:
    """Службові значення поля mark (офіційний клієнт, calendar-panel):
    ±19 — «не допущено» (н/д), ±20 — екзамен без оцінки (порожньо).
    Повертає (оцінка для показу | None, не_допущено)."""
    key = str(raw).strip() if raw is not None else ""
    if key in ("19", "-19"):
        return None, True
    if key in ("20", "-20"):
        return None, False
    return raw, False


def norm_lesson(l: dict) -> dict:
    wd = str(l.get("week_day") or "")
    mark_shown, not_allowed = _split_special_mark(l.get("mark"))
    return {
        "date": l.get("date") or "",
        "weekday": _WEEKDAYS_UK[int(wd)] if (wd.isascii() and wd.isdigit()) and 1 <= int(wd) <= 7 else wd,
        "lesson_no": l.get("lesson") or 0,
        "start": (l.get("started_at") or "")[:5],
        "end": (l.get("finished_at") or "")[:5],
        "subject": l.get("subject_name") or "",
        "theme": l.get("lesson_theme") or "",
        "teacher": l.get("teacher_name") or "",
        "room": l.get("room_name") or "",
        "mark": mark_shown,
        "not_allowed": not_allowed,
        "attendance": l.get("attendance"),
        "was": l.get("was"),
        "was_type": l.get("was_type"),
        "mark_type": l.get("mark_type"),
        "homeworks": [
            {"id": h.get("id_domzad"), "mark": h.get("mark"),
             "status": h.get("status")}
            for h in (l.get("homeworks") or [])
        ],
        "video": bool(l.get("video_link")),
        # екзамен: поле exam — ОБ'ЄКТ з evaluation_date;
        # у звичайних уроків це порожній список [] або відсутність поля
        "exam": bool(l.get("exam")) and not isinstance(l.get("exam"), list),
    }


def marks_view(payloads: dict[str, Any]) -> dict:
    """statistic/marks → предмети з середнім + повна стрічка оцінок.

    Секція stat_marks_year тягнеться БЕЗ period → вся історія (2023+),
    а не лише навчальний рік. Fallback — stat_marks (period=month).

    type_work тут має ті самі id, що й mark_type уроків розкладу
    (енам MyStat): 0 тестування, 1 курсова, 2 екзамен, 3 самостійна,
    4 практична, 5 класна, 6 контрольна, 7 тематична.
    """
    raw = payloads.get("stat_marks_year")
    if not isinstance(raw, list) or not raw:
        raw = payloads.get("stat_marks")

    def _iso_or_ymd(m: dict) -> str:
        """mark_date ISO; fallback y-m-d із компонентів — з ведучими нулями,
        інакше рядкове сортування recent/items сплутає місяці
        («2026-10-15» < «2026-9-1» лексикографічно)."""
        if m.get("mark_date"):
            return str(m["mark_date"])
        try:
            return (f"{int(str(m['y'])):04d}-{int(str(m['m'])):02d}"
                    f"-{int(str(m['d'])):02d}")
        except (KeyError, TypeError, ValueError):
            return ""

    marks: list[dict] = []
    if isinstance(raw, list):
        for m in raw:
            try:
                mark_val = float(m.get("mark"))
            except (TypeError, ValueError):
                continue
            try:
                tw = int(str(m.get("type_work") or "").strip() or "0")
            except ValueError:
                tw = 0
            marks.append({
                "date": _iso_or_ymd(m),
                "mark": int(mark_val) if mark_val.is_integer() else mark_val,
                "subject": m.get("name_spec") or "",
                "theme": m.get("theme") or "",
                "teacher": m.get("fio_teach") or "",
                "photo": m.get("photo_pas") or "",
                "comment": m.get("comment") or "",
                "type_work": tw or None,
            })

    per_subject: dict[str, dict] = {}
    for m in marks:
        s = per_subject.setdefault(m["subject"],
                                   {"subject": m["subject"], "marks": []})
        s["marks"].append(m["mark"])
    subjects = [
        {
            "subject": s["subject"],
            "avg": round(sum(s["marks"]) / len(s["marks"]), 1),
            "count": len(s["marks"]),
            "best": max(s["marks"]),
            "worst": min(s["marks"]),
        }
        for s in per_subject.values()
    ]
    subjects.sort(key=lambda x: (-x["count"], x["subject"]))

    items = sorted(marks, key=lambda m: str(m["date"]), reverse=True)
    recent = items[:8]
    overall_avg = (round(sum(m["mark"] for m in marks) / len(marks), 1)
                   if marks else None)
    return {"overall_avg": overall_avg, "total_marks": len(marks),
            "subjects": subjects, "recent": recent, "items": items}


def dashboard_view(payloads: dict[str, Any]) -> dict:
    hw = homework_view(payloads)
    # ключ снапшота — «schedule_week» (як у SYNC_PLAN/DASHBOARD_SECTIONS);
    # «week» тут означало payloads.get("week") → None і порожню картку
    # «сьогодні/за тиждень» на дашборді.
    sched = schedule_view(payloads, "schedule_week")
    today_iso = _kyiv_today().isoformat()
    today_lessons = next((d["lessons"] for d in sched["days"]
                          if d["date"] == today_iso), [])

    profile = payloads.get("profile")
    profile = profile if isinstance(profile, dict) else {}
    storage = profile.get("user_storage")
    storage = storage if isinstance(storage, dict) else {}
    photo = ""
    profiles_map = profile.get("user_profiles")
    if isinstance(profiles_map, dict):
        for by_branch in profiles_map.values():
            if not isinstance(by_branch, dict):
                continue
            for profiles in by_branch.values():
                if isinstance(profiles, list) and profiles:
                    photo = str(profiles[0].get("photo") or "") \
                        if profiles and isinstance(profiles[0], dict) else ""
                    break
            if photo:
                break

    marks = marks_view(payloads)

    config = payloads.get("config")
    config = config if isinstance(config, dict) else {}
    group = config.get("group")
    group = group if isinstance(group, dict) else {}
    group_name = str(group.get("name_tgroups") or "")

    return {
        "user": {
            "fio": profile.get("name")
            or " ".join(p for p in (storage.get("lastname"),
                                    storage.get("firstname")) if p)
            or profile.get("username") or "",
            "photo_url": photo,
            "branch_alias": profile.get("branch_alias") or "",
            "branch_name": branch_display_name(profile.get("branch_alias")),
            "logbook_id": str(profile.get("id") or ""),
            "id_user_storage": str(profile.get("id_user_storage") or ""),
            "lang": profile.get("lang") or "uk",
            "group_name": group_name,
        },
        "balances": balances_view(payloads),
        "homework_counts": hw["counts"],
        "nearest_deadlines": hw["nearest_deadlines"],
        "today_lessons": today_lessons,
        "week_lessons_total": sched["total_lessons"],
        "marks_summary": {
            "overall_avg": marks["overall_avg"],
            "recent": marks["recent"][:4],
        },
    }


# ================================================================ M4e: здача ДЗ

MAX_FILE_SIZE = 25 * 1024 * 1024  # константа з бандла MyStat

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _safe_filename(name: str | None) -> str:
    """Безпечне ім'я файлу для zip/fs-сервісу (захист від zip-slip):
    обидва роздільники (слеш і бекслеш) → беремо лише останній компонент, прибираємо
    літеру диска, `..`, керуючі символи й ведучі крапки. Порожнє → «file»."""
    raw = (name or "").replace("\\", "/")
    raw = _DRIVE_RE.sub("", raw)
    base = raw.rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ord(ch) >= 32 and ord(ch) != 127)
    base = base.replace("..", "").lstrip(".").strip()
    return base[:200] or "file"


async def submit_homework(db, account: MystatAccount, homework_id: int,
                          comment: str,
                          files: list[tuple[str, bytes, str]],
                          zip_mode: str = "auto",
                          zip_name: str = "",
                          compress_level: int = 6,
                          rename: bool = True,
                          link: str = "",
                          provider: str = "itstep",
                          open_in_browser: bool = False) -> dict:
    """Здавання домашки. Живий контракт, знятий З ОФІЦІЙНОГО КЛІЄНТА
    користувачем і підтверджений probe_answertext.py (відкат через delete):
      1) якщо є файли: GET /user/file-token → POST {url} multipart
         directory+files[] → [{link, ...}]
      2) POST /homework/create  application/json:
         {"id": <id завдання>, "answerText": <текст або «»>,
          "filename": "<fs-посилання через кому>|null",
          "clientFilename": "<оригінальні імена>|null"}
         → 201 {id: id здачі, status: 2, ...}; 422/3004 = не прийнято.
         Текст лягає в communication_history (stud_answer НЕ пишеться),
         тому чистий текст працює взагалі без файлів.
      3) відкат: DELETE /homework/delete/{id здачі}

    Пакування в .zip: MyStat приймає не більше одного файла на здачу, тому
    якщо файлів кілька — вони пакуються в один архів перед завантаженням
    у fs-сервіс. `zip_mode`: "auto" (архів лише коли файлів > 1),
    "always" (завжди архівувати, навіть один файл), "off" (без архівації,
    кілька файлів → помилка hw_zip_required). `zip_name` — ім'я архіва
    без розширення, `compress_level` — 0..9 (0 = зберігання без стиснення).
    """
    if not files and not (comment or "").strip() and not (link or "").strip():
        # ні файла, ні тексту, ні посилання — немає чого здавати
        raise ApiError(422, "hw_file_required", "files",
                       "at_least_one_file_or_comment")
    if link and not (link or "").strip().lower().startswith(("http://",
                                                             "https://")):
        raise ApiError(422, "hw_link_invalid", "link",
                       "must_be_http_or_https_url")
    if provider not in ("itstep", "m1"):
        raise ApiError(422, "hw_provider_invalid", "provider",
                       "must_be_itstep_or_m1")

    try:
        token = decrypt_secret(account.access_token_enc)
    except ValueError:
        account.status = "needs_relogin"
        db.commit()
        raise ApiError(401, "account_needs_relogin", "__all__",
                       "token_unreadable_after_restart_re_link_account")

    language = account.language or "uk"
    uid = account.id_user_storage or None
    alias = account.branch_alias

    # zip-slip / path traversal: нормалізуємо імена ДО будь-якого пакування
    files = [(_safe_filename(n), d, ct) for n, d, ct in files]
    for n, d, _ct in files:
        if len(d) > MAX_FILE_SIZE:
            raise ApiError(422, "hw_file_too_large", "files", n)

    # 0) іменування + пакування. Правила:
    #    • базове ім'я — «Прізвище_Ім'я» з fio акаунта (або кастомний
    #      текст користувача з підстановками {surname}/{name}/{n});
    #    • кілька файлів → ЗАВЖДИ один .zip (mapi приймає лише один файл);
    #    • один файл → напряму, якщо це png/jpg; інакше теж у .zip;
    #    • всередині архіва файли перейменовуються: Прізвище_Ім'я.ext,
    #      а за кількох файлів одного типу — Прізвище_Ім'я_1.ext, _2, …
    #      (для кожного розширення рахунок окремий).
    _bad = '\\/:*?"<>|'
    def _clean(s: str) -> str:
        return "".join(ch for ch in s if ch not in _bad).strip(".")

    if files:
        def _is_image(n: str) -> bool:
            ext = (n or "").rsplit(".", 1)[-1].lower()
            return ext in ("png", "jpg", "jpeg")

        parts = (account.fio or "").split()
        surname = _clean(parts[0]) if parts else ""
        firstname = _clean(parts[1]) if len(parts) > 1 else ""
        custom = (zip_name or "").strip()
        if custom:
            custom = (custom.replace("{surname}", surname)
                            .replace("{name}", firstname))
            base = _clean(custom)
        else:
            base = "_".join(p for p in (surname, firstname) if p)
        base = base or f"homework-{homework_id}"

        level = max(0, min(int(compress_level), 9))

        def _pack(items: list[tuple[str, bytes, str]]) -> tuple[str, bytes]:
            """Архівує items у <base>.zip з перейменуванням по типах."""
            arc_base = _clean(base.replace("{n}", str(len(items)))) \
                if "{n}" in base else base
            counters: dict[str, int] = {}
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w",
                                 compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=level or None) as zf:
                for n, d, _ct in items:
                    dot = (n or "").rfind(".")
                    ext = (n[dot:] if dot >= 0 else "").lower()
                    ext_key = ext.lstrip(".")
                    k = counters.get(ext_key, 0) + 1
                    counters[ext_key] = k
                    if not rename:
                        # оригінальні імена файлів без змін
                        zf.writestr(_safe_filename(n), d)
                        continue
                    if "{n}" in base:
                        inner = _clean(base.replace("{n}", str(k)))
                    else:
                        inner = base if k == 1 and \
                            sum(1 for x in items
                                if (x[0] or "").rsplit(".", 1)[-1].lower()
                                == ext_key) == 1 else f"{base}_{k}"
                    zf.writestr(f"{inner}{ext}", d)
            data = buf.getvalue()
            if len(data) > MAX_FILE_SIZE:
                raise ApiError(422, "hw_file_too_large", "files",
                               f"{arc_base}.zip")
            return f"{arc_base}.zip", data

        if len(files) == 1 and zip_mode != "always" and _is_image(files[0][0]):
            # один png/jpg → напряму (за rename — перейменувати)
            n, d, ct = files[0]
            if not rename:
                files = [(_safe_filename(n), d, ct)]
            else:
                dot = (n or "").rfind(".")
                files = [(f"{base}{n[dot:].lower() if dot >= 0 else ''}", d, ct)]
        else:
            # кілька файлів, або один не-зображення, або always → один .zip
            arc_name, arc_data = _pack(files)
            files = [(arc_name, arc_data, "application/zip")]

    # 1) файли розв'язку → fs-сервіс (інший хост + інший JWT)
    links: list[str] = []
    names: list[str] = []
    if files:
        try:
            r = await ms.request_async(
                "GET", f"/v1/mystat/{alias}/user/file-token",
                token=token, language=language, user_id=uid)
        except httpx.HTTPError as exc:
            raise _mapi_unreachable(exc) from exc
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
        if not furl or not hwdir:
            raise ApiError(502, "mystat_unavailable", "__all__",
                           "file_service_unconfigured")
        form = [("files[]", (n, d, ct or "application/octet-stream"))
                for n, d, ct in files]
        ftoken = ft.get("token") or ""
        if not ftoken:
            raise ApiError(502, "mystat_unavailable", "__all__",
                           "file_token_missing")
        # ОКРЕМИЙ клієнт із довгим таймаутом: до 10×25 МБ через спільний
        # (15с sync_timeout) вмирало на повільних каналах
        up_timeout = httpx.Timeout(120.0, connect=15.0)
        try:
            async with httpx.AsyncClient(transport=ms._async_transport,
                                         timeout=up_timeout) as fx:
                up = await fx.post(furl, files=form,
                                   data={"directory": hwdir},
                                   headers={"Authorization":
                                            f"Bearer {ftoken}",
                                            "X-Language": language})
        except httpx.HTTPError as exc:
            raise _mapi_unreachable(exc) from exc
        if up.status_code not in (200, 201):
            raise ApiError(502, "mystat_unavailable", "__all__",
                           f"file_upload_status_{up.status_code}")
        try:
            links = [x["link"] for x in up.json()
                     if isinstance(x, dict) and x.get("link")]
        except Exception:
            links = []
        if not links:
            raise ApiError(502, "mystat_unavailable", "__all__",
                           "file_upload_empty")
        names = [n for n, _d, _ct in files]
    # «Своє посилання»: замість файлу на fs-сервері itstep можна віддати
    # будь-який URL — він лягає тим самим елементом у filename/create,
    # тож MyStat відкриє його як звичайний файл розв'язку.
    if link:
        from urllib.parse import urlparse, unquote
        _p = urlparse(link)
        _seg = [s for s in unquote(_p.path).split("/") if s]
        _ln = _seg[-1] if _seg else (_p.netloc or "solution")
        if not files:
            # ім'я «файлу» в MyStat: кастомний текст або Фамілія_Ім'я
            _parts = (account.fio or "").split()
            _base = "_".join(p for p in (_clean(_parts[0]) if _parts else "",
                                         _clean(_parts[1]) if len(_parts) > 1 else "")
                             if p) or "solution"
            _custom = (zip_name or "").strip()
            if _custom:
                _ln = _clean(_custom.replace("{surname}", _base.split("_")[0]
                                             if _base else "")
                                 .replace("{name}", _base.split("_")[1]
                                          if "_" in _base else ""))
        names.append(_ln or "solution")
        links.append(link.strip())
    produced_links = links

    # ── M1 Provider: замість прямого fs-лінка/URL — наше коротке
    #    посилання /api/v1/files/<slug>. mapi не переписує шлях,
    #    бо він збігається з його файловим патерном; відкриття веде
    #    на наш роутер (302 або сторінка-галерея).
    public_slug_url: str | None = None
    m1_link_row = None
    if provider == "m1":
        from app.services import links as m1links
        links_mod = m1links

        # метадані ДЗ зі снапшота (без додаткового запиту в mapi)
        hw_title = hw_subject = hw_due = ""
        try:
            _snap = (db.query(Snapshot)
                     .filter(Snapshot.account_id == account.id,
                             Snapshot.section == "homework").first())
            _grp_list = json.loads(_snap.payload) if _snap else []
            for _grp in (_grp_list or []):
                if not isinstance(_grp, dict):
                    continue
                for _item in _grp.get("data") or []:
                    if isinstance(_item, dict) and \
                            int(_item.get("id") or 0) == int(homework_id):
                        hw_title = str(_item.get("theme")
                                       or _item.get("title") or "")[:255]
                        hw_subject = str(_item.get("name_spec")
                                         or _item.get("subject") or "")[:255]
                        hw_due = str(_item.get("overdue_time")
                                     or _item.get("due_date")
                                     or _item.get("date") or "")[:32]
                        break
        except Exception:
            pass
        # у M1 Provider файл ↔ посилання не змішуються: файл → target =
        # fs-лінк; без файлів → target = URL користувача (link).
        # Тільки текст (коментар) без файлів і лінка — теж валідна здача:
        # M1-посилання тоді просто не створюється, у mapi йде filename=null.
        src_url = (produced_links[0] if files else (link or "").strip())
        if src_url:
            media = None
            if files and open_in_browser:
                media = m1links.build_media_manifest(files)
            m1_link_row = m1links.create_link(
                user_id=account.user_id, account_id=account.id,
                account_seq=account.user_seq, homework_id=homework_id,
                hw_title=hw_title, hw_subject=hw_subject, hw_due=hw_due,
                kind="file" if files else "url", target_url=src_url,
                media=media)
            public_slug_url = m1links.public_url(m1_link_row)
            links = [public_slug_url]
            names = names or ["solution"]

    # 2) створення здавання — єдиний живий контракт, знятий З КЛІЄНТА
    #    користувачем і підтверджений probe_answertext.py:
    #    JSON {id, answerText, filename|null, clientFilename|null};
    #    текст лягає в communication_history (stud_answer не пишеться).
    # посилання йде як «файл» у filename (див. нижче), тому в answerText
    # лягає лише коментар користувача.
    _answer_text = (comment or "").strip()

    async def _create(tok: str):
        try:
            return await ms.request_async(
                "POST", f"/v1/mystat/{alias}/homework/create",
                token=tok, language=language, user_id=uid,
                json_body={"id": homework_id,
                           "answerText": _answer_text,
                           "filename": ",".join(links) or None,
                           "clientFilename": ",".join(names) or None})
        except httpx.HTTPError as exc:
            raise _mapi_unreachable(exc) from exc

    resp = await _create(token)
    if resp.status_code == 401:
        try:
            new_token = await ms.refresh_once(token, language, user_id=uid)
        except ms.MystatError as exc:
            raise ApiError(502, "mystat_unavailable", "__all__",
                           "mystat_temporarily_unreachable_during_refresh") from exc
        if new_token is None:
            account.status = "needs_relogin"
            db.commit()
            raise ApiError(401, "account_needs_relogin", "__all__",
                           "refresh_failed_re_enter_credentials")
        token = new_token
        ms.set_account_token(account, new_token)
        db.commit()
        resp = await _create(new_token)

    if resp.status_code == 401:
        account.status = "needs_relogin"
        db.commit()
        raise ApiError(401, "account_needs_relogin", "__all__",
                       "mystat_session_rejected_re_enter_credentials")
    if resp.status_code not in (200, 201):
        # mapi не прийняв здачу → наше коротке посилання не лишається жити
        if m1_link_row is not None:
            try:
                ldb = links_mod.new_session()
                _row = ldb.get(links_mod.M1Link, m1_link_row.slug)
                if _row is not None:
                    _row.active = False
                    ldb.commit()
                ldb.close()
            except Exception:
                pass
        if resp.status_code == 422:
            raise ApiError(422, "hw_submit_rejected", "__all__",
                           "mystat_cant_save_homework")
        raise ApiError(502, "mystat_unavailable", "__all__",
                       f"hw_create_status_{resp.status_code}")
    try:
        out = resp.json()
    except Exception:
        out = {}

    # 4) інвалідуємо кеш домашки — наступна вибірка піде в mapi
    (db.query(Snapshot)
     .filter(Snapshot.account_id == account.id,
             Snapshot.section == "homework")
     .delete())
    db.commit()

    return {"submission_id": out.get("id"),
            "status": out.get("status", 2),
            "files": produced_links,
            "archived": bool(names) and names[0].lower().endswith(".zip")
            and len(names) == 1,
            "archived_name": names[0] if names else None,
            "m1_link": links_mod.link_view(m1_link_row)
            if m1_link_row is not None else None}


# ================================================================ news / shop

_CURRENCY_MAP = {"COI": "coins", "DIA": "cristals", "BEV": "beavers"}
_ORDER_STATUS_LABEL = {1: "нове", 3: "нове", 2: "скасовано", 5: "скасовано",
                       4: "закрито"}


def _first_img(v: Any) -> str | None:
    """mapi віддає image то рядком (news), то списком URL (shop)."""
    if isinstance(v, list):
        return str(v[0]) if v else None
    return str(v) if v else None


def news_view(payloads: dict[str, Any]) -> dict:
    """news → стрічка новин для картки на Головній + модалки.

    Жива форма (diag 2026-08-26): [{id, title, preview_text,
    image: str|list, is_viewed, mark, avg_mark,
    published_at: 'YYYY-MM-DD HH:MM:SS', created_by_fullname}].
    """
    raw = payloads.get("news")
    items: list[dict] = []
    for x in raw if isinstance(raw, list) else []:
        if not isinstance(x, dict) or x.get("id") is None:
            continue
        items.append({
            "id": x.get("id"),
            "title": x.get("title") or "",
            "preview": x.get("preview_text") or "",
            "image": _first_img(x.get("image")),
            "is_viewed": bool(x.get("is_viewed")),
            "published_at": str(x.get("published_at") or "")[:10],
            "author": x.get("created_by_fullname") or None,
            "mark": x.get("mark"),
        })
    items.sort(key=lambda i: i["published_at"], reverse=True)
    return {"items": items,
            "unread": sum(1 for i in items if not i["is_viewed"])}


async def news_detail(db, account: MystatAccount, news_id: int) -> dict:
    """Живий GET /news/{id} — повний текст (HTML) для модалки."""
    r = await _live(db, account, "GET", f"/news/{news_id}")
    if r.status_code != 200:
        raise ApiError(502, "mystat_unavailable", "__all__",
                       f"news_detail_status_{r.status_code}")
    try:
        d = r.json()
    except Exception:
        d = {}
    if isinstance(d, dict) and isinstance(d.get("data"), dict):
        d = d["data"]
    if not isinstance(d, dict):
        # mapi повернув несподівану форму (list/рядок) — не валимо в 500
        raise ApiError(502, "mystat_unavailable", "__all__",
                       "news_detail_bad_payload")
    return {
        "id": d.get("id"),
        "title": d.get("title") or "",
        "text": d.get("text") or "",
        "preview": d.get("preview_text") or "",
        "image": _first_img(d.get("image")),
        "published_at": str(d.get("published_at") or "")[:10],
        "author": d.get("created_by_fullname") or None,
        "mark": d.get("mark"),
        "avg_mark": d.get("avg_mark"),
    }


def shop_view(payloads: dict[str, Any]) -> dict:
    """shop/products + shop/orders → каталог і замовлення в нашому форматі.

    prices: [{price: '231.00', currency: 'COI'|'DIA'|'BEV', type: 'default'}];
    order.products: [{product_id, title, quantity, image: [URL],
    order_product_price: [{price: 196, currency}]}];
    статуси UI з бандла ByDv-LLj2: 1|3 нове, 2|5 скасовано, 4 закрито.
    """
    prods = payloads.get("shop_products")
    products: list[dict] = []
    for p in prods if isinstance(prods, list) else []:
        if not isinstance(p, dict) or p.get("id") is None:
            continue
        prices = p.get("prices") if isinstance(p.get("prices"), list) else []
        pr = prices[0] if prices else {}
        # у товару може бути ДЕКІЛЬКА цін (монети І кристали —
        # live: currencies ['COI','DIA']) — віддаємо всі, фронт покаже обидва
        prices_all = [
            {"price": x.get("price"), "min_price": x.get("min_price"),
             "currency": _CURRENCY_MAP.get(x.get("currency"), "coins")}
            for x in prices if isinstance(x, dict)
        ]
        products.append({
            "id": p.get("id"),
            "title": p.get("title") or "",
            "text": p.get("text") or "",
            "image": _first_img(p.get("image")),
            "quantity": p.get("quantity"),
            "price": pr.get("price"),
            "min_price": pr.get("min_price"),
            "currency": _CURRENCY_MAP.get(pr.get("currency"), "coins"),
            "prices": prices_all,
            "properties": [
                {"name": x.get("name") or "", "value": x.get("value") or ""}
                for x in (p.get("properties") or [])
                if isinstance(x, dict)
            ],
        })
    orders_raw = payloads.get("shop_orders")
    orders: list[dict] = []
    for o in orders_raw if isinstance(orders_raw, list) else []:
        if not isinstance(o, dict) or o.get("id") is None:
            continue
        items: list[dict] = []
        totals: dict[str, float] = {}
        total = 0.0
        cur = "coins"
        for it in o.get("products") or []:
            if not isinstance(it, dict):
                continue
            prices = it.get("order_product_price") or []
            pr = prices[0] if prices else {}
            price = float(pr.get("price") or 0)
            qty = int(it.get("quantity") or 1)
            # товар коштує УСІ валюти одночасно (COI І DIA) — сумуємо кожну окремо
            for x in prices if isinstance(prices, list) else []:
                if not isinstance(x, dict):
                    continue
                cur_x = _CURRENCY_MAP.get(x.get("currency"), "coins")
                totals[cur_x] = totals.get(cur_x, 0.0) \
                    + float(x.get("price") or 0) * qty
            total += price * qty
            cur = _CURRENCY_MAP.get(pr.get("currency"), "coins")
            items.append({
                "product_id": it.get("product_id"),
                "title": it.get("title") or "",
                "quantity": qty,
                "image": _first_img(it.get("image")),
                "price": price,
                "currency": cur,
                "prices": [
                    {"price": float(x.get("price") or 0),
                     "currency": _CURRENCY_MAP.get(x.get("currency"), "coins")}
                    for x in prices if isinstance(x, dict)
                ],
            })
        st = o.get("status")
        orders.append({
            "id": o.get("id"),
            "uuid": o.get("uuid"),
            "status": st,
            "status_label": _ORDER_STATUS_LABEL.get(st, "?"),
            "cancelled": st in (2, 5),
            # 4 = «закрито» — теж негарячий заказ: фронт гасить його сірим
            "archived": st in (2, 4, 5),
            "created_at": str(o.get("created_at") or "")[:10],
            # довіряємо серверу: live присилав can_discard=True при status=5
            "can_discard": bool(o.get("can_discard")),
            "items": items,
            "total": round(total, 2),
            "currency": cur,
            # суми по КОЖНІЙ валюті: товар завжди коштує монети І кристали
            "totals": [{"price": round(v, 2), "currency": cur_x}
                       for cur_x, v in totals.items()],
        })
    return {"products": products, "orders": orders}


async def _live(db, account: MystatAccount, method: str, sub: str, *,
                json_body: Any = None) -> Any:
    """Живий запит /shop|/news + ланцюжок refresh (як у homework_card).
    Повертає httpx.Response — коди 4xx прокидуємо назовні."""
    try:
        token = decrypt_secret(account.access_token_enc)
    except ValueError:
        account.status = "needs_relogin"
        db.commit()
        raise ApiError(401, "account_needs_relogin", "__all__",
                       "token_unreadable_after_restart_re_link_account")

    language = account.language or "uk"
    uid = account.id_user_storage or None
    path = f"/v1/mystat/{account.branch_alias}{sub}"

    async def go(tok: str):
        try:
            return await ms.request_async(method, path, token=tok,
                                          language=language, user_id=uid,
                                          json_body=json_body)
        except httpx.HTTPError as exc:
            raise _mapi_unreachable(exc) from exc

    r = await go(token)
    if r.status_code == 401:
        try:
            new_tok = await ms.refresh_once(token, language, user_id=uid)
        except ms.MystatError as exc:
            raise ApiError(502, "mystat_unavailable", "__all__",
                           "mystat_temporarily_unreachable_during_refresh") from exc
        if new_tok:
            ms.set_account_token(account, new_tok)
            db.commit()
            r = await go(new_tok)
        else:
            account.status = "needs_relogin"
            db.commit()
            raise ApiError(401, "account_needs_relogin", "__all__",
                           "refresh_failed_re_enter_credentials")
    return r


async def shop_create_order(db, account: MystatAccount,
                            product_id: int, quantity: int) -> dict:
    """POST /shop/create-order (merchant Gaming — оплата бонусами).
    Тіло задокументоване в MYSTAT_API.md (з бандла MyStat)."""
    resp = await _live(db, account, "POST", "/shop/create-order",
                       json_body={"products": [
                           {"product_id": product_id, "quantity": quantity}],
                           "merchant": "Gaming"})
    if resp.status_code in (200, 201):
        # інвалідуємо кеш замовлень і товарами (залишок міг змінитись)
        (db.query(Snapshot)
         .filter(Snapshot.account_id == account.id,
                 Snapshot.section.in_(["shop_orders", "shop_products"]))
         .delete(synchronize_session=False))
        db.commit()
    try:
        out = resp.json()
    except Exception:
        out = {}
    return {"status": resp.status_code, "data": out}


async def shop_discard_order(db, account: MystatAccount, uuid: str) -> dict:
    """PUT /shop/discard-order {uuid} — тіло з бандла chunk-5nAkkiT82.js."""
    resp = await _live(db, account, "PUT", "/shop/discard-order",
                       json_body={"uuid": uuid})
    if resp.status_code in (200, 201):
        (db.query(Snapshot)
         .filter(Snapshot.account_id == account.id,
                 Snapshot.section == "shop_orders")
         .delete(synchronize_session=False))
        db.commit()
    try:
        out = resp.json()
    except Exception:
        out = {}
    return {"status": resp.status_code, "data": out}


# ========================================================= qr / лідерборд

def qr_view(payloads: dict[str, Any]) -> dict:
    """students/get-qr-code → data:image/png;base64 (жива відповідь —
    голий JSON-рядок, без обгортки)."""
    qr = payloads.get("qr")
    if not isinstance(qr, str) or not qr:
        raise ApiError(502, "mystat_unavailable", "__all__", "qr_missing")
    return {"qr": qr}


def _lb_row(x: Any) -> dict:
    return {
        "id": x.get("id_stud"),
        "fio": x.get("fio_stud") or "",
        "photo": x.get("photo") or None,
        "amount": x.get("amount"),
        "position": x.get("position"),
        "is_new": bool(x.get("is_new")),
    }


def _lb_rows(arr: Any, key: str) -> list[dict]:
    out = [_lb_row(x) for x in (arr if isinstance(arr, list) else [])
           if isinstance(x, dict)]
    if key == "new_students":
        # новенькі без позиції — сортуємо за кількістю монет
        out.sort(key=lambda r: r["amount"] or 0, reverse=True)
    else:
        out.sort(key=lambda r: (r["position"] is None, r["position"] or 0))
    return out


def _lb_points(node: Any) -> dict:
    d = node if isinstance(node, dict) else {}
    return {"total": d.get("totalCount"),
            "position": d.get("studentPosition"),
            "week_diff": d.get("weekDiff"),
            "month_diff": d.get("monthDiff")}


def profile_login_from_snapshot(db, account_id: int) -> str:
    """Логін MyStat зі снапшота профілю: username на верхньому рівні."""
    row = (db.query(Snapshot)
           .filter(Snapshot.account_id == account_id,
                   Snapshot.section == "profile")
           .first())
    if row is None:
        return ""
    import json as _json
    try:
        payload = _json.loads(row.payload)
    except Exception:
        return ""
    return str(payload.get("username") or "")


_LB_SCOPE_LABEL_UK = {"group": "Група", "stream": "Потік"}
_LB_SCOPE_LABEL_EN = {"group": "Group", "stream": "Stream"}
_LB_PERIOD_LABEL_UK = {
    "month": "Місяць", "semester": "Семестр", "year": "Рік",
    "all_time": "За весь час", "week": "Тиждень", "day": "День",
}
_LB_PERIOD_LABEL_EN = {
    "month": "Month", "semester": "Semester", "year": "Year",
    "all_time": "All time", "week": "Week", "day": "Day",
}


def leaderboard_view(payloads: dict[str, Any]) -> dict:
    """progress/leader-points + leader-table → наша форма.

    Живий leader-table дає НЕ суцільний рейтинг, а три блоки:
      top (позиції 1-3) · other (позиції навколо ТВОЄЇ, напр. 11-14)
      · new_students (без позиції). Склеювати їх в один список не можна —
    у списку виникав «розрив» 3 → 11. Тому віддаємо секціями.

    Гілки mapi різні: школа - month/semester/year, академія -
    month/all_time (перевірено на живому акаунті 2026-08). Тому
    охоплення і періоди читаємо ДИНАМІЧНО з відповіді. Тип акаунта
    визначаємо за набором періодів → branch: academy / school /
    unknown (невідома гілка отримує англійські підписи)."""
    tbl = payloads.get("leader_table") or {}
    pts = payloads.get("leader_points") or {}
    if not isinstance(tbl, dict):
        tbl = {}
    if not isinstance(pts, dict):
        pts = {}

    def sec(node: dict) -> dict:
        return {
            "top": _lb_rows(node.get("top"), "top"),
            "nearby": _lb_rows(node.get("other"), "other"),
            "new_students": _lb_rows(node.get("new_students"), "new_students"),
        }

    # 1) фактичні охоплення/періоди: секція = вузол зі списками
    #    top/other/new_students (порожні вузли на кшталт {} - пропускаємо,
    #    щоб не малювати порожні кнопки).
    sections: dict[str, dict[str, dict]] = {}
    scopes_meta: list[dict] = []
    all_periods: set[str] = set()
    for scope_key, scope_node in tbl.items():
        if not isinstance(scope_node, dict):
            continue  # sliding_rating тощо
        periods: dict[str, dict] = {}
        pmeta: list[dict] = []
        for pk, node in scope_node.items():
            if not isinstance(node, dict) or not any(
                    isinstance(node.get(k), list)
                    for k in ("top", "other", "new_students")):
                continue
            periods[str(pk)] = sec(node)
            pmeta.append({"key": str(pk), "label": str(pk)})
            all_periods.add(str(pk))
        if periods:
            sections[str(scope_key)] = periods
            scopes_meta.append({"key": str(scope_key), "label": str(scope_key),
                                "periods": pmeta})

    # 2) тип акаунта → мова підписів: відома гілка - укр, невідома - англ.
    if "all_time" in all_periods:
        branch = "academy"
    elif "semester" in all_periods or "year" in all_periods:
        branch = "school"
    else:
        branch = "unknown"
    scope_lbl = (_LB_SCOPE_LABEL_UK if branch != "unknown"
                 else _LB_SCOPE_LABEL_EN)
    period_lbl = (_LB_PERIOD_LABEL_UK if branch != "unknown"
                  else _LB_PERIOD_LABEL_EN)
    for sm in scopes_meta:
        sm["label"] = scope_lbl.get(sm["key"], sm["key"].capitalize())
        for pm in sm["periods"]:
            pm["label"] = period_lbl.get(pm["key"], pm["key"].capitalize())

    # 3) points: ключі = охоплення з таблиці + наявні у leader-points
    scope_keys = list(dict.fromkeys(
        list(sections.keys())
        + [str(k) for k, v in pts.items() if isinstance(v, dict)]))
    return {
        "points": {s: _lb_points(pts.get(s)) for s in scope_keys},
        "sliding_rating": bool(tbl.get("sliding_rating")),
        "branch": branch,
        "scopes": scopes_meta,
        "sections": sections,
    }


# ================================================================ M5: платежі

_DAYS_UK = {
    "monday": "Понеділок", "tuesday": "Вівторок", "wednesday": "Середа",
    "thursday": "Четвер", "friday": "П'ятниця", "saturday": "Субота",
    "sunday": "Неділя",
}


def payments_view(payloads: dict) -> dict:
    """Платежі: зведення + наступний платіж + історія (нормалізована)."""
    info = payloads.get("payment_info") or {}
    nxt = payloads.get("payment_next") or {}
    history = payloads.get("payment_history") or []
    if isinstance(history, dict):
        history = history.get("data") or history.get("items") or []
    hist = [{
        "date": h.get("date"),
        "amount": h.get("amount"),
        "currency": h.get("currency") or "UAH",
        "description": h.get("description") or "",
    } for h in history if isinstance(h, dict)]
    return {
        "full_name": info.get("full_name"),
        "one_c_code": info.get("one_c_code"),
        "online_link": info.get("online_link"),
        "instruction_link": info.get("instruction_link"),
        "student_cost": info.get("student_cost"),
        # debtor_status: 0 — все ок, більше — є заборгованість
        "debtor_status": nxt.get("debtor_status", 0),
        "debt_amount": nxt.get("amount") or 0,
        "next_date": nxt.get("date_start") or nxt.get("pay_date_start"),
        "next_critical": nxt.get("date_critical"),
        "history": hist,
        "schedule": payloads.get("payment_schedule"),
    }


def clubs_view(payloads: dict) -> dict:
    """Клуби: список + абонементи + баланс + транзакції."""
    clubs = payloads.get("clubs") or []
    if isinstance(clubs, dict):
        clubs = clubs.get("data") or clubs.get("items") or []
    out = []
    for c in clubs:
        if not isinstance(c, dict):
            continue
        sched = [{
            "day": _DAYS_UK.get((x or {}).get("day_of_week", ""),
                                (x or {}).get("day_of_week")),
            "from": (x or {}).get("time_from", "")[:5],
            "to": (x or {}).get("time_to", "")[:5],
        } for x in (c.get("schedules") or []) if isinstance(x, dict)]
        out.append({
            "id": c.get("id"),
            "name": c.get("name"),
            "category": c.get("club_category"),
            "sub_type": c.get("sub_type"),
            "cost": c.get("cost"),
            "debt": c.get("debt") or 0,
            "address": c.get("address"),
            "image": c.get("image"),
            "description": c.get("description"),
            "status": c.get("status"),
            "schedules": sched,
            "teachers": [e.get("fio") for e in (c.get("employees") or [])
                         if isinstance(e, dict) and e.get("fio")],
            "abonements": c.get("abonements") or [],
        })
    tx = payloads.get("club_transactions") or []
    if isinstance(tx, dict):
        tx = tx.get("data") or tx.get("items") or []
    return {
        "clubs": out,
        "abonements": payloads.get("club_abonements") or [],
        "balance": (payloads.get("club_balance") or {}).get("amount", 0),
        "transactions": tx,
    }


def contacts_view(payloads: dict, branch: str = "") -> dict:
    """Контакти філії — passthrough (структура плоска і так) + наші доповнення:
      • `director` — завжди першим у списку контактів (фото з assets);
      • `teach_contacts[].photo` — фото викладача з нашої бази
        (services/teacher_photos.py), бо MyStat його тут не віддає."""
    from app.services import teacher_photos

    src = payloads.get("contacts") or {}
    out = dict(src) if isinstance(src, dict) else {}
    d = teacher_photos.DIRECTOR
    out["director"] = {"name": d["name"], "role": d["role"],
                       "photo": f"/api/teacher-photos/{d['photo_key']}"}
    teach = []
    for t in out.get("teach_contacts") or []:
        if isinstance(t, dict):
            t = dict(t)
            t["photo"] = teacher_photos.photo_path_for(
                branch, str(t.get("fio_teach") or ""), t.get("id_teach"))
        teach.append(t)
    out["teach_contacts"] = teach
    return out


async def reference_file(db, account: MystatAccount,
                         type_: int = 1) -> tuple[bytes, str, str | None]:
    """GET /contacts/get-reference-data?type=N — файл (blob) від MyStat.

    Повертає (content, content_type, content_disposition)."""
    resp = await _live(db, account, "GET",
                       f"/contacts/get-reference-data?type={type_}")
    if resp.status_code != 200:
        raise ApiError(resp.status_code, "reference_error", "__all__",
                       "failed_to_fetch_reference")
    return (resp.content,
            resp.headers.get("content-type", "application/octet-stream"),
            resp.headers.get("content-disposition"))


async def contacts_send(db, account: MystatAccount, subject: str,
                        message: str, target: str = "ceo",
                        teacher: str | None = None) -> dict:
    """POST /contacts/send-ceo | send-teach — тіло як у формі офіційного
    MyStat (chunk Oo33piqv, mailForm.value): завжди всі чотири поля
    {teacher, id_problem, subject, message}.
      • викладач: teacher = ЧИСЛОВИЙ id_teach (не ПІБ — інакше MyStat
        відповідає «Перевірте правильність заповнення полів»);
      • директор: teacher = null; id_problem = null в обох випадках."""
    tid: int | str | None = None
    if target == "teach":
        path = "/contacts/send-teach"
        raw = (teacher or "").strip()
        if not re.fullmatch(r"[0-9]{1,12}", raw):
            raise ApiError(422, "validation_error", "teacher", "teacher_required")
        tid = int(raw)
    else:
        path = "/contacts/send-ceo"
    body = {"teacher": tid, "id_problem": None,
            "subject": subject, "message": message}
    resp = await _live(db, account, "POST", path, json_body=body)
    try:
        out = resp.json()
    except Exception:
        out = {}
    return {"status": resp.status_code, "data": out}


async def club_buy(db, account: MystatAccount,
                   club_id: int, abonement_id: int) -> dict:
    """POST /club/buy-abonement {abonement_id, entity_id} — тіло з бандла.

    Успіх → снек payment_successful; інвалідуємо клубні кеші."""
    resp = await _live(db, account, "POST", "/club/buy-abonement",
                       json_body={"abonement_id": abonement_id,
                                  "entity_id": club_id})
    if resp.status_code in (200, 201):
        (db.query(Snapshot)
         .filter(Snapshot.account_id == account.id,
                 Snapshot.section.in_(["club_balance", "club_transactions",
                                       "club_abonements"]))
         .delete(synchronize_session=False))
        db.commit()
    try:
        out = resp.json()
    except Exception:
        out = {}
    return {"status": resp.status_code, "data": out}


# ================================================== нагороди / прогрес


def awards_view(payloads: dict[str, Any]) -> dict:
    """custom-awards/items + custom-awards/balance → наша форма.

    items — ОБ'ЄКТ по категоріях {body:[…], mouth:[…], …}; елемент:
    {id, img, prices:[{value, currency:"BEV"}], purchased, equipped, default}.
    balance — {"beavers":<int>} (парсер терпить {beavers:{value|all}} і {balance})."""
    raw_bal = payloads.get("awards_balance")
    beavers = 0
    if isinstance(raw_bal, dict):
        b = raw_bal.get("beavers")
        if isinstance(b, dict):  # {beavers:{value, temp_value, all}}
            b = b.get("all") or b.get("value") or 0
            b = 0 if isinstance(b, dict) else b
        if isinstance(b, (int, float)):
            beavers = int(b)
        elif "balance" in raw_bal:  # альтернативна форма
            try:
                beavers = int(raw_bal["balance"])
            except (TypeError, ValueError):
                beavers = 0

    raw_items = payloads.get("awards_items")
    categories: list[dict] = []
    if isinstance(raw_items, dict):
        for code, arr in raw_items.items():
            if not isinstance(arr, list):
                continue
            items = []
            for x in arr:
                if not isinstance(x, dict):
                    continue
                prices = [p for p in (x.get("prices") or [])
                          if isinstance(p, dict)]
                price = prices[0].get("value") if prices else 0
                currency = (prices[0].get("currency") or "BEV") if prices \
                    else "BEV"
                items.append({
                    "id": x.get("id"),
                    "img": x.get("img") or "",
                    "price": price if isinstance(price, int) else 0,
                    "currency": currency,
                    "purchased": bool(x.get("purchased")),
                    "equipped": bool(x.get("equipped")),
                    "free": not prices,
                })
            categories.append({"key": str(code), "items": items})
    return {"beavers": beavers, "categories": categories}


def progress_view(payloads: dict[str, Any]) -> dict:
    """statistic/progress → графіки середнього балу по місяцях.

    Жива форма (docs/live_shapes/statistic_progress_year.json):
    {data:[{chart_type, chart_models:[{date, points, previous_points,
    has_rasp}], average_point, prev_average_point}], total_average_point,
    prev_total_average_point}. points=null = місяць ще не настав."""
    raw = payloads.get("stat_progress")
    data = raw.get("data") if isinstance(raw, dict) else raw
    charts: list[dict] = []
    for ch in (data if isinstance(data, list) else []):
        if not isinstance(ch, dict):
            continue
        points: list[dict] = []
        seen: dict[str, dict] = {}
        for m in (ch.get("chart_models") or []):
            if not isinstance(m, dict):
                continue
            month = str(m.get("date") or "")[:7]
            if not month:
                continue
            entry = {
                "month": month,
                "points": m.get("points"),
                "prev": m.get("previous_points"),
            }
            dup = seen.get(month)
            if dup is None:
                seen[month] = entry
                points.append(entry)
            else:
                # живий mapi віддає один місяць ДВІЧІ (помічено на
                # 2026-09): фронт падав each_key_duplicate. Склеюємо:
                # пріоритет у останнього запису, але не затираємо null'ом
                # уже відомі значення
                if entry["points"] is not None:
                    dup["points"] = entry["points"]
                if entry["prev"] is not None:
                    dup["prev"] = entry["prev"]
        charts.append({
            "chart_type": ch.get("chart_type"),
            "average": ch.get("average_point"),
            "prev_average": ch.get("prev_average_point"),
            "points": points,
        })
    return {
        "charts": charts,
        "total_average": raw.get("total_average_point")
        if isinstance(raw, dict) else None,
        "prev_total_average": raw.get("prev_total_average_point")
        if isinstance(raw, dict) else None,
    }


async def awards_buy(db, account: MystatAccount, item_ids: list[int]) -> dict:
    """POST /custom-awards/items/buy {items:[id,…]} — купити предмети
    аватара за бобрів. Успіх → інвалідуємо кеш каталогу й балансу."""
    resp = await _live(db, account, "POST", "/custom-awards/items/buy",
                       json_body={"items": item_ids})
    if resp.status_code in (200, 201):
        (db.query(Snapshot)
         .filter(Snapshot.account_id == account.id,
                 Snapshot.section.in_(["awards_items", "awards_balance"]))
         .delete(synchronize_session=False))
        db.commit()
    try:
        out = resp.json()
    except Exception:
        out = {}
    return {"status": resp.status_code, "data": out}


async def awards_equip(db, account: MystatAccount, item_id: int) -> dict:
    """POST /custom-awards/items/equip {item_id} — надіти предмет на аватар."""
    resp = await _live(db, account, "POST", "/custom-awards/items/equip",
                       json_body={"item_id": item_id})
    if resp.status_code in (200, 201):
        (db.query(Snapshot)
         .filter(Snapshot.account_id == account.id,
                 Snapshot.section == "awards_items")
         .delete(synchronize_session=False))
        db.commit()
    try:
        out = resp.json()
    except Exception:
        out = {}
    return {"status": resp.status_code, "data": out}
