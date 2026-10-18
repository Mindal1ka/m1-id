"""Sync Engine (M3, повністю асинхронний): план задач → снапшоти + статуси.

Усі запити до mapi йдуть паралельно (asyncio + семафор), прогрес оновлюється
з завершенням кожної задачі — онбординг бачить швидкий живий чеклист.
"""
from __future__ import annotations

import asyncio
import json
import threading
import traceback
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.clock import naive_kyiv_now
from app.core.security import decrypt_secret, encrypt_secret
from app.db.base import SessionLocal
from app.db.models import MystatAccount, Snapshot
from app.services import mystat_client as ms


@dataclass(frozen=True)
class Task:
    section: str      # ключ снапшота
    path: str         # повний шлях mapi разом із query-рядком
    label: str        # підпис для онбордингу
    critical: bool = False
    method: str = "GET"   # /auth/* у MyStat — POST (MYSTAT_API §3)!


# ── FEATURE FLAGS ────────────────────────────────────────────────────
# Клуби вимкнено (секції не тягнуться з mapi і не летять на клієнт).
# Вернути: поставити True тут + розкоментувати вкладку в +page.svelte (TABS).
CLUBS_ENABLED = False


def _club_tasks(b: str) -> list[Task]:
    return [
        Task("clubs", f"{b}/club/get-clubs", "Клуби: список"),
        Task("club_abonements", f"{b}/club/abonements", "Клуби: абонементи"),
        Task("club_balance", f"{b}/club/get-balance", "Клуби: баланс"),
        Task("club_transactions", f"{b}/club/transactions", "Клуби: транзакції"),
    ]


def build_plan(branch_alias: str, today_ym: str | None = None) -> list[Task]:
    b = f"/v1/mystat/{branch_alias}" if branch_alias else "/v1/mystat/pl"
    # N-M9 fix: «поточний місяць/тиждень» — за київським часом
    # (mapi-дати — у київській зоні, не в UTC сервера).
    now_kyiv = naive_kyiv_now()
    ym = today_ym or now_kyiv.strftime("%Y-%m")
    # ПОТОЧНИЙ понеділок (ISO): date_filter=понеділок (слово) mapi тягне як
    # «тиждень ПОПЕРЕДНЬОГО понеділка» — у понеділок це минулий тиждень, і
    # дашборд/віджет «Сьогодні» показують застарілі пари (знято зі
    # снапшотів 31.08: plain-фільтр віддав 24–30.08, ISO-фільтр — 31.08–
    # 06.09). Слово залежить ще й від мови акаунта (uk/ru) — ISO-дата
    # однакова всюди і збігається з параметризованою секцією schedule_week@.
    mon = (now_kyiv - timedelta(days=now_kyiv.weekday())).strftime("%Y-%m-%d")
    return [
        Task("profile", "/v1/mystat/auth/me", "Профіль", critical=True,
             method="POST"),
        Task("config", f"{b}/config", "Налаштування філії"),
        Task("counters", f"{b}/count/page-counters", "Лічильники"),
        Task("balances", f"{b}/gaming/get-balances", "Баланси"),
        Task("schedule_month",
             f"{b}/schedule/get-month?type=month&date_filter={ym}", "Розклад місяць"),
        Task("schedule_week",
             f"{b}/schedule/get-month?type=week&date_filter={mon}",
             "Розклад тиждень"),
        Task("homework", f"{b}/homework/list?limit=100", "Домашка"),
        Task("stat_marks", f"{b}/statistic/marks?period=month", "Оцінки"),
        # без period mapi віддає ПОВНУ історію оцінок (груз ~94 КБ, перевірено
        # live) — інакше чіпи обрізаються поточним навчальним роком (з 2025-09)
        Task("stat_marks_year", f"{b}/statistic/marks",
             "Оцінки (вся історія)"),
        Task("stat_attendance", f"{b}/statistic/attendance?period=month",
             "Відвідування"),
        Task("shop_products", f"{b}/shop/products?page=1&per_page=100",
             "Магазин: товари"),
        Task("shop_orders", f"{b}/shop/orders", "Магазин: замовлення"),
        Task("qr", f"{b}/students/get-qr-code", "QR-код"),
        Task("leader_points", f"{b}/progress/leader-points",
             "Лідерборд: позиція"),
        Task("leader_table", f"{b}/progress/leader-table",
             "Лідерборд: таблиця"),
        Task("stat_progress", f"{b}/statistic/progress?period=month", "Прогрес"),
        Task("news", f"{b}/news?per_page=15", "Новини"),
        Task("awards_items", f"{b}/custom-awards/items", "Нагороди: предмети"),
        Task("awards_balance", f"{b}/custom-awards/balance", "Нагороди: баланс"),
        # M5: платежі / клуби / контакти
        Task("payment_info", f"{b}/payment", "Платежі: зведення"),
        Task("payment_next", f"{b}/payment/get-next-payment", "Платежі: наступний"),
        Task("payment_history", f"{b}/payment/history", "Платежі: історія"),
        Task("payment_schedule", f"{b}/payment/schedule", "Платежі: графік"),
        *(_club_tasks(b) if CLUBS_ENABLED else []),
        Task("contacts", f"{b}/contacts", "Контакти філії"),
    ]


# ------------------------------------------------------------- стан

_lock = threading.Lock()
_states: dict[int, dict] = {}
# Посилання на фонові задачі: event loop тримає Task слабким посиланням,
# без явного holding GC може зібрати задачу посеред синхронізації.
_bg_tasks: set[asyncio.Task] = set()

# Авторетрай: 2 повтори (30с, 2хв) після тимчасової помилки синку.
_RETRY_MAX = 3
_RETRY_DELAYS = (30, 120)

# ── WS-хаб: живий пуш стану синку відкритим клієнтам сайту ──
# Кожен підписник — WebSocket + мапа pk акаунта → user_seq (фронт
# оперує user_seq). _update() після кожної зміни стану пушить JSON
# усім, хто підписаний на цей акаунт; пуш не ламає синк (усі помилки
# ковтаються, мертві сокети відписуються).
_ws_clients: "list[tuple[Any, dict[int, int]]]" = []
_ws_loop: "asyncio.AbstractEventLoop | None" = None


def _ws_seq_map(account_pks: list[int]) -> dict[int, int]:
    from app.db.models import MystatAccount
    from app.db.base import SessionLocal
    db = SessionLocal()
    try:
        rows = (db.query(MystatAccount.id, MystatAccount.user_seq)
                .filter(MystatAccount.id.in_(account_pks)).all())
        return {pk: seq for pk, seq in rows}
    finally:
        db.close()


def sync_ws_register(ws: "Any", account_pks: list[int]) -> None:
    global _ws_loop
    _ws_loop = asyncio.get_running_loop()
    _ws_clients.append((ws, _ws_seq_map(account_pks)))


def sync_ws_unregister(ws: "Any") -> None:
    global _ws_clients
    _ws_clients = [(w, m) for w, m in _ws_clients if w is not ws]


async def _ws_push(account_pk: int, state: dict) -> None:
    import json as _json
    dead: list[Any] = []
    for ws, seq_map in list(_ws_clients):
        seq = seq_map.get(account_pk)
        if seq is None:
            continue
        try:
            await ws.send_text(_json.dumps({"account": seq, **state},
                                           ensure_ascii=False))
        except Exception:
            dead.append(ws)
    for ws in dead:
        sync_ws_unregister(ws)


def _broadcast_state(account_pk: int) -> None:
    if not _ws_clients:
        return
    state = get_state(account_pk)
    target = _ws_loop
    if target is None or target.is_closed():
        return  # немає жодного підписаного сокета — пушити нікуди
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is target:
        running.create_task(_ws_push(account_pk, state))
    else:
        # виклик з іншого потоку або з thread-fallback loop синку: сокети
        # живуть у ГОЛОВНОМУ loop, тож корутину мусимо запланувати саме там
        try:
            asyncio.run_coroutine_threadsafe(_ws_push(account_pk, state),
                                             target)
        except RuntimeError:
            pass  # головний loop закрито (shutdown) — пуш не критичний


def _utcnow_naive() -> datetime:
    """Наївний UTC без deprecation-warning (utcnow() deprecated)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_state(account_id: int) -> dict:
    with _lock:
        return deepcopy(_states.get(account_id, {"status": "idle", "steps": []}))


def is_running(account_id: int) -> bool:
    with _lock:
        return _states.get(account_id, {}).get("status") in ("running", "queued")


def _update(account_id: int, **fields) -> None:
    with _lock:
        _states.setdefault(account_id, {"status": "idle", "steps": []})
        _states[account_id].update(fields)
    _broadcast_state(account_id)


# ---------------------------------------------------------------- запуск


def start_sync(account_id: int) -> bool:
    """Запустити асинхронну синхронізацію. False — уже виконується."""
    with _lock:
        state = _states.setdefault(account_id, {"status": "idle", "steps": []})
        if state.get("status") in ("running", "queued"):
            return False
        # Слот резервуємо СИНХРОННО: раніше status="running" ставився
        # лише всередині _run_sync (коли задача ще не стартувала), і два
        # швидкі запити (link-автосинк + POST /{id}/sync, подвійний клік)
        # обидва проходили is_running() → дві паралельні синхронізації
        # одного акаунта (подвійне навантаження на mapi, мигаючий статус).
        state["status"] = "queued"
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            threading.Thread(
                target=lambda: asyncio.run(_run_sync(account_id)), daemon=True
            ).start()
        except Exception:
            _update(account_id, status="idle")  # не лишаємо вічний queued
            raise
    else:
        task = loop.create_task(_run_sync(account_id))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
    return True


# ---------------------------------------------------------------- рушій


async def _run_sync(account_id: int) -> None:
    # Авторетрай із backoff: тимчасовий збій (мережа/5xx/таймаут mapi)
    # не лишає статус «error» назавжди — ретраїмо до RETRY_MAX разів.
    # needs_relogin ретраю не підлягає (без дій користувача не виправити).
    for attempt in range(_RETRY_MAX):
        await _run_sync_once(account_id)
        state = get_state(account_id)
        if state.get("status") != "error":
            return
        err = str(state.get("error", ""))
        if "needs_relogin" in err or "account_not_found" in err:
            return  # повторний вхід / видалення — тільки дією користувача
        if attempt < _RETRY_MAX - 1:
            _update(account_id, status="running", error=None,
                    current="Повторна спроба синку…")
            await asyncio.sleep(_RETRY_DELAYS[attempt])


async def _run_sync_once(account_id: int) -> None:
    db = SessionLocal()
    client = ms.open_async_client()
    try:
        account = db.get(MystatAccount, account_id)
        if account is None:
            _update(account_id, status="error", error="account_not_found")
            return

        plan = build_plan(account.branch_alias)
        steps = [{"section": t.section, "label": t.label,
                  "status": "pending"} for t in plan]
        _update(account_id, status="running", steps=steps, error=None,
                progress={"done": 0, "total": len(plan)},
                started_at=_utcnow_naive().isoformat())

        token_holder = {"token": decrypt_secret(account.access_token_enc)}
        language = account.language or "uk"
        refresh_lock = asyncio.Lock()
        sem = asyncio.Semaphore(5)
        done_counter = {"n": 0}

        async def fetch(task: Task, tok: str):
            return await client.request(
                task.method.upper(),
                f"{ms._base_url()}{task.path}",
                headers=ms._headers(tok, language,
                                    account.id_user_storage or None),
            )

        async def run_one(i: int, task: Task) -> None:
            async with sem:
                steps[i]["status"] = "running"
                _update(account_id, steps=deepcopy(steps),
                        current=task.label)
                try:
                    resp = await fetch(task, token_holder["token"])

                    if resp.status_code == 401:
                        # 401 → один спільний refresh → повтор (рішення №1)
                        async with refresh_lock:
                            new_token = await ms.refresh_once(
                                token_holder["token"], language,
                                user_id=account.id_user_storage or None)
                            if new_token is None:
                                account.status = "needs_relogin"
                                db.commit()
                                raise RuntimeError("token_needs_relogin")
                            ms.set_account_token(account, new_token)
                            db.commit()
                            token_holder["token"] = new_token
                        resp = await fetch(task, token_holder["token"])
                    resp.raise_for_status()

                    payload = resp.json() if resp.content else None
                    _save_snapshot(db, account.id, task.section, payload)
                    steps[i]["status"] = "done"
                except Exception as exc:  # noqa: BLE001
                    steps[i]["status"] = "failed"
                    steps[i]["error"] = str(exc)[:160]
                    if task.critical:
                        raise
                finally:
                    done_counter["n"] += 1
                    _update(account_id, steps=deepcopy(steps),
                            progress={"done": done_counter["n"],
                                      "total": len(plan)})

        results = await asyncio.gather(
            *(run_one(i, t) for i, t in enumerate(plan)),
            return_exceptions=True,
        )
        if any(isinstance(r, BaseException) for r in results):
            raise next(r for r in results if isinstance(r, BaseException))

        account.last_synced_at = _utcnow_naive()
        account.status = "active"
        db.commit()
        _update(account_id, status="done", finished_at=_utcnow_naive().isoformat(),
                progress={"done": len(plan), "total": len(plan)}, current=None)

    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        msg = str(exc)[:300]
        status = "error"
        if "needs_relogin" in msg:
            acc = db.get(MystatAccount, account_id)
            if acc is not None:
                acc.status = "needs_relogin"
                db.commit()
        _update(account_id, status=status, error=msg,
                finished_at=_utcnow_naive().isoformat())
    finally:
        await client.aclose()
        db.close()


def _save_snapshot(db, account_id: int, section: str, payload) -> None:
    from sqlalchemy.exc import IntegrityError

    raw = json.dumps(payload, ensure_ascii=False)
    for _attempt in range(2):
        # SELECT-then-INSERT переганяється з паралельним web-запитом за ту саму
        # секцію (app_data теж пише снапшоти) → UNIQUE(account_id,
        # section). Повтор після rollback = UPDATE по чужій вставці.
        row = (db.query(Snapshot)
               .filter(Snapshot.account_id == account_id,
                       Snapshot.section == section)
               .first())
        if row is None:
            row = Snapshot(account_id=account_id, section=section, payload=raw)
            db.add(row)
        else:
            row.payload = raw
            row.fetched_at = _utcnow_naive()
        try:
            db.commit()
            return
        except IntegrityError:
            db.rollback()  # конкурент вставив раніше — повторимо як UPDATE
