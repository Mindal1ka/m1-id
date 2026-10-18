"""Notify-сокет MyStat: миттєві події + Автооцінювання уроків.

Це «швидкий шлях» у гібриді з поллером:
  • поллер (30 хв, розмазаний) - ДЖЕРЕЛО ПРАВДИ, лишається як є;
  • сокет (wss://notify-socket-logbook.itstep.org, socket.io) шле події
    миттєво - на подію ми робимо ТОЧКОВИЙ перезапит розділів цього
    акаунта в mapi → детекти змін поллера спрацьовують одразу.

Що робить на події:
  socket_notification / _list / _counter → fast-path: перезапитати секції
    акаунта (з тротлінгом 120с і повагою тихих годин). Оновлюються і
    снапшоти сайту, і TG-сповіщення (якщо ввімкнені).
  socket_notification_handler {handler: 'evaluation_notification'} →
    Автооцінювання: POST /v1/mystat/{alias}/students/evaluate-lesson
    {mark_lesson: 5, mark_teach: 5, comment: "", id: evaluation_lesson_id}
    - саме так це робить офіційний клієнт (MYSTAT_API §14). Коди mapi:
    84221 NOT_FOUND · 84222 ALREADY_USED · 84223 CLOSED_TODAY (оцінити
    можна лише в день заняття) · 84224 INCORRECT_MARK · 84225 SAVE_ERROR.

Підключення (1 з'єднання на акаунт, як в офіційного клієнта):
  query: {alias: <branch_alias>}   auth: {token: <access_token>}
  headers: {"ngrok-skip-browser-warning": "69420"}
  on connect (через 1с) → join_room {rooms: [global, <profile>_personal_<uid>],
  user_id, unread: true}. Ре-коннекти робимо САМІ (reconnection=False):
  при кожному підключенні читаємо СВІЖИЙ токен (офіційний клієнт оновлює
  auth при reconnect так само).

Тихі години 23:00-05:00 (з конфіга Telegram-акаунта; дефолт - увімкнені):
  mapi не смикаємо. Урок, що прийшов уночі, ПИШЕМО в auto_eval_log
  (status='pending') і оцінюємо вранці - інший шлях втратити оцінку.

Fail-soft: без python-socketio в requirements сокет вимкнено, API живе.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time as _time
from collections import deque
from datetime import datetime, time as dtime, timedelta, timezone
from urllib.parse import urlencode

from app.core.clock import naive_kyiv_now
from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.db.base import SessionLocal
from app.db.models import (
    AutoEvalLog,
    MystatAccount,
    SocketAccountConfig,
    TelegramAccountConfig,
    TelegramLink,
    utcnow,
)
from app.services import app_data
from app.services import mystat_client as ms

_log = logging.getLogger("m1id.socket")

try:  # fail-soft: нема пакета - сокет вимкнено, решта працює
    import socketio  # type: ignore
except Exception:  # pragma: no cover
    socketio = None

NOTIFY_URL = "https://notify-socket-logbook.itstep.org"
NGROK_HEADER = {"ngrok-skip-browser-warning": "69420"}
FASTPATH_MIN_INTERVAL = 120.0  # не частіше, ніж раз на 2 хв на акаунт
EVAL_ALREADY_USED = 84222
EVAL_CLOSED_TODAY = 84223

# статус для сайту: account_id → {...}
_status: dict[int, dict] = {}
_tasks: dict[int, asyncio.Task] = {}
_stopping = False
_fastpath_ts: dict[int, float] = {}
_pending_loop: asyncio.Task | None = None


# ------------------------------------------------------------------ стан

def _st(account_id: int, **kw) -> dict:
    s = _status.setdefault(account_id, {
        "connected": False, "connected_at": None, "last_event_at": None,
        "events": 0, "evals_ok": 0, "last_error": "",
    })
    s.update(kw)
    return s


def status_for(account_id: int) -> dict:
    return dict(_status.get(account_id, {}))


def is_running_for(account_id: int) -> bool:
    t = _tasks.get(account_id)
    return t is not None and not t.done() and _status.get(account_id, {}) \
        .get("connected") is True


def _is_quiet_now(account_id: int) -> bool:
    """Тихі години 23:00-05:00 за часом сервера. Конфіг - з Telegram
    (це єдина «галочка ночі» в системі); немає конфіга → увімкнені."""
    db = SessionLocal()
    try:
        cfg = (db.query(TelegramAccountConfig)
               .filter(TelegramAccountConfig.account_id == account_id)
               .first())
        enabled = cfg.quiet_hours if cfg is not None else True
    finally:
        db.close()
    if not enabled:
        return False
    # N-M9 fix: межі доби — за КИЄВОМ, не за локальним часом сервера.
    t = naive_kyiv_now().time()
    return t >= dtime(23, 0) or t < dtime(5, 0)


# ------------------------------------------------------------------ токен

class _PermanentSkip(Exception):
    """Акаунт не може підключитись (релогін) - не молотимо reconnect."""


async def _fresh_token(acc: MystatAccount) -> str:
    """Декриптуємо токен; якщо ось-ось згниє - проактивний refresh.
    Кидає _PermanentSkip якщо сесію відхилено."""
    if acc.status == "disabled":
        raise _PermanentSkip("account_disabled")
    if not acc.access_token_enc:
        raise _PermanentSkip("no_token")
    try:
        token = decrypt_secret(acc.access_token_enc)
    except ValueError as exc:
        acc.status = "needs_relogin"
        raise _PermanentSkip("token_unreadable") from exc
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if acc.token_expires_at is not None \
            and acc.token_expires_at <= now + timedelta(seconds=120):
        new_tok = await ms.refresh_once(
            token, acc.language or "uk",
            user_id=acc.id_user_storage or None)
        if not new_tok:
            acc.status = "needs_relogin"
            raise _PermanentSkip("refresh_rejected")
        ms.set_account_token(acc, new_tok)
        return new_tok
    return token


# ---------------------------------------------------------------- events

def _rooms_for(acc: MystatAccount) -> list[str]:
    """Кімнати як в офіційного клієнта: global + персональна. Групові
    (stream/dir) - лиш для загальних розсилок; персональні події приходять
    у <profile>_personal_<id_user_storage>. Профіль зберігаємо student
    (продукт про студентів; parent-профіль підключимо, коли з'явиться)."""
    return ["global", f"student_personal_{acc.id_user_storage or ''}"]


async def _on_connect(sio, account_id: int) -> None:
    _st(account_id, connected=True,
        connected_at=utcnow().isoformat(timespec="seconds"), last_error="")
    _log.info("socket: акаунт %d підключено", account_id)
    db = SessionLocal()
    try:
        acc = db.get(MystatAccount, account_id)
        if acc is None:
            return
        await asyncio.sleep(1.0)  # як в офіційному клієнті
        await sio.emit("join_room", {
            "rooms": _rooms_for(acc),
            "user_id": acc.id_user_storage or "",
            "unread": True,
        })
    finally:
        db.close()


async def _on_disconnect(account_id: int, *args) -> None:
    _st(account_id, connected=False)
    _log.info("socket: акаунт %d від'єднано", account_id)


async def _on_event(account_id: int, event_name: str, *payload) -> None:
    """Спільна точка для notify-подій: статус + fast-path refresh."""
    import time as _time

    _st(account_id, last_event_at=utcnow().isoformat(timespec="seconds"),
        events=_status.get(account_id, {}).get("events", 0) + 1)
    now = _time.monotonic()
    if now - _fastpath_ts.get(account_id, 0.0) < FASTPATH_MIN_INTERVAL:
        return  # серія подій → один перезапит
    _fastpath_ts[account_id] = now
    if _is_quiet_now(account_id):
        return  # уночі mapi не смикаємо - поллер розбереться зранку
    try:
        from app.telegram import poller as pl
        await pl.refresh_account_now(account_id)
    except Exception as exc:
        _log.warning("socket fastpath account=%d: %r", account_id, exc)


async def _on_handler(account_id: int, payload: dict) -> None:
    if not isinstance(payload, dict):
        return
    handler = str(payload.get("handler") or "")
    if handler != "evaluation_notification":
        await _on_event(account_id, f"handler:{handler}")
        return
    data = payload.get("data")
    if isinstance(data, str):
        import json as _json
        try:
            data = _json.loads(data)
        except Exception:
            data = {}
    if not isinstance(data, dict):
        return
    lesson_id = str(data.get("evaluation_lesson_id") or "")
    if not lesson_id:
        return
    await _auto_eval(account_id, lesson_id,
                     str(data.get("theme") or ""),
                     str(data.get("teach_name") or ""))


# ------------------------------------------------------- автооцінювання

def _auto_eval_enabled(db, account_id: int) -> SocketAccountConfig | None:
    scfg = (db.query(SocketAccountConfig)
            .filter(SocketAccountConfig.account_id == account_id).first())
    if scfg is None or not scfg.socket_enabled or not scfg.auto_eval:
        return None
    return scfg


async def _auto_eval(account_id: int, lesson_id: str,
                     theme: str, teach_name: str) -> None:
    db = SessionLocal()
    try:
        acc = db.get(MystatAccount, account_id)
        if acc is None or acc.status == "disabled":
            return
        scfg = _auto_eval_enabled(db, account_id)
        if scfg is None:
            return
        # dedupe: повторна подія (reconnect, черга) не оцінює вдруге
        row = (db.query(AutoEvalLog)
               .filter(AutoEvalLog.account_id == account_id,
                       AutoEvalLog.lesson_id == lesson_id).first())
        if row is not None:
            return
        row = AutoEvalLog(account_id=account_id, lesson_id=lesson_id[:64],
                          theme=theme[:255], teach_name=teach_name[:255],
                          mark_lesson=scfg.eval_mark_lesson,
                          mark_teach=scfg.eval_mark_teach,
                          status="pending")
        db.add(row)
        try:
            db.commit()
        except Exception:
            db.rollback()  # паралельна подія вже записала - вона оцінить
            return
        if _is_quiet_now(account_id):
            _log.info("autoeval: урок %s відкладено (тихі години) - "
                      "оцінимо зранку", lesson_id)
            return
        try:
            await _rate_pending_row(db, acc, row)
        except ms.MystatError as exc:
            # mapi моргнув: урок лишається 'pending' → дорахує loop черги
            _log.warning("autoeval: mapi недоступний (%r) - урок %s "
                         "лишається в черзі", exc, lesson_id)
    finally:
        db.close()


# ------------------------------------------------- pacування автооцінювань
# Якщо модуль був вимкнений довго, при включенні пачка накопичених уроків
# оцінювалась поспіль → mapi часом «відбиває» (ліміт/блок на спам
# evaluate-lesson). Правило: перші 4 оцінювання за останні 10 с — без
# затримки, кожне наступне — не частіше ніж раз на 5с.
_EVAL_FAST_BUDGET = 4
_EVAL_MIN_GAP = 5.0
_EVAL_WINDOW = 10.0

# часові мітки нещодавніх оцінювань + наступний вільний момент (per account)
_eval_times: dict[int, deque] = {}
_eval_next_free: dict[int, float] = {}
_eval_guard = threading.Lock()


def _eval_claim_slot(account_id: int) -> float:
    """→ скільки секунд зачекати перед оцінюванням (0 = одразу)."""
    now = _time.monotonic()
    with _eval_guard:
        dq = _eval_times.setdefault(account_id, deque())
        while dq and now - dq[0] > _EVAL_WINDOW:
            dq.popleft()
        if len(dq) < _EVAL_FAST_BUDGET:
            at = now  # бюджет швидких оцінювань ще не вичерпано
        else:
            at = max(now, _eval_next_free.get(account_id, now))
        dq.append(at)
        _eval_next_free[account_id] = at + _EVAL_MIN_GAP
    return max(0.0, at - now)


async def _rate_pending_row(db, acc: MystatAccount, row: AutoEvalLog) -> None:
    """Один урок → evaluate-lesson. Успіх → TG-повідомлення (якщо ввімкнено)."""
    # pacування: після 4 швидких оцінювань — не частіше ніж раз на 5с
    delay = _eval_claim_slot(acc.id)
    if delay > 0:
        _log.info("autoeval: pacування - урок %s чекає %.1fс (після пачки)",
                  row.lesson_id, delay)
        await asyncio.sleep(delay)
    alias = acc.branch_alias or "pl"
    token = await _fresh_token(acc)
    db.commit()  # прапори/токен
    resp = await ms.request_async(
        "POST", f"/v1/mystat/{alias}/students/evaluate-lesson",
        token=token, language=acc.language or "uk",
        user_id=acc.id_user_storage or None,
        json_body={
            "mark_lesson": row.mark_lesson,
            "mark_teach": row.mark_teach,
            "comment": "",
            "id": int(row.lesson_id) if (row.lesson_id.isascii() and row.lesson_id.isdigit())
            else row.lesson_id,
        })
    code = None
    try:
        err = resp.json()
        if isinstance(err, dict):
            code = err.get("code") or err.get("errorCode")
    except Exception:
        pass
    # Успіх = ЛЮБИЙ 2xx. Живий mapi на збереження оцінки віддає
    # 205 Reset Content (порожнє тіло) - офіційний клієнт (Angular,
    # бачив у бандлах) вважає успіхом будь-який 2xx і показує
    # lesson_evaluation_success. Тільки 200 приймати не можна:
    # оцінка реально зберігається (+1 кристал), а ми писали
    # «error (None, http 205)» і не слали TG.
    if 200 <= resp.status_code < 300:
        row.status = "ok"
        row.rated_at = utcnow()
        db.commit()
        _st(acc.id, evals_ok=_status.get(acc.id, {}).get("evals_ok", 0) + 1)
        await _notify_eval(acc, row)
        return
    if code == EVAL_ALREADY_USED:
        row.status = "already"  # вже оцінено - це успіх для нас
        row.rated_at = utcnow()
    elif code == EVAL_CLOSED_TODAY:
        # оцінити можна лише в день заняття: пізніше вже безглуздо
        row.status = "closed"
        row.error_code = int(code)
    else:
        row.status = "error"
        row.error_code = int(code) if isinstance(code, (int, float)) else None
    db.commit()
    if row.status == "already":
        # не попередження: «вже оцінено» - штатна відповідь сервера
        # (наприклад урок оцінили раніше вручну або минула спроба)
        _log.info("autoeval account=%d lesson=%s → already (http %s)",
                  acc.id, row.lesson_id, resp.status_code)
    else:
        _log.warning("autoeval account=%d lesson=%s → %s (%s, http %s)",
                     acc.id, row.lesson_id, row.status, code, resp.status_code)


async def _notify_eval(acc: MystatAccount, row: AutoEvalLog) -> None:
    """TG «урок оцінено автоматично» - окрема галочка в конфізі акаунта."""
    db = SessionLocal()
    try:
        cfg = (db.query(TelegramAccountConfig)
               .filter(TelegramAccountConfig.account_id == acc.id).first())
        if cfg is None or not cfg.notify_auto_eval or not cfg.chat_id:
            return
        link = (db.query(TelegramLink)
                .filter(TelegramLink.user_id == acc.user_id).first())
        if link is None:
            return
        n_accs = (db.query(MystatAccount)
                  .filter(MystatAccount.user_id == acc.user_id,
                          MystatAccount.status != "disabled").count())
        from app.telegram import poller as pl
        prefix = pl._acc_prefix(acc) if n_accs > 1 else ""
        lines = [prefix + "⭐ <b>Урок оцінено автоматично</b>"]
        if row.theme:
            lines.append(f"Тема: {pl.tg._esc(row.theme)}")
        if row.teach_name:
            # у боті — без приписки «School» (у БД ім'я лишається як є)
            from app.services.teacher_photos import display_name
            lines.append(f"Викладач: {pl.tg._esc(display_name(row.teach_name))}")
        lines.append(f"Оцінка: {row.mark_lesson} за урок · "
                     f"{row.mark_teach} викладачу")
        await pl._notify(cfg.chat_id, "\n".join(lines))
    except Exception as exc:
        _log.warning("autoeval notify failed: %r", exc)
    finally:
        db.close()


async def _process_pending_loop() -> None:
    """Щохвилини: відкладені оцінки (тихі години) - щойно вікно скінчилось."""
    while not _stopping:
        await asyncio.sleep(60)
        try:
            # N-M9 fix: вікно тихих годин — за київським часом.
            tk = naive_kyiv_now().time()
            if tk >= dtime(23, 0) or tk < dtime(5, 0):
                continue
            db = SessionLocal()
            try:
                pending = (db.query(AutoEvalLog)
                           .filter(AutoEvalLog.status == "pending").all())
                for row in pending:
                    acc = db.get(MystatAccount, row.account_id)
                    if acc is None or acc.status == "disabled":
                        # акаунт видалено/вимкнено: без фіксації рядок назавжди
                        # висіла б у pending і пересканувалася б щохвилини
                        row.status = "skipped"
                        db.commit()
                        continue
                    scfg = _auto_eval_enabled(db, row.account_id)
                    if scfg is None:
                        # автооцінювання вимкнули: фіксуємо skipped, інакше
                        # db.close() відкотить статус → вічний рескан
                        row.status = "skipped"
                        db.commit()
                        continue
                    try:
                        await _rate_pending_row(db, acc, row)
                    except _PermanentSkip as exc:
                        row.status = "error"
                        db.commit()
                        _log.warning("autoeval pending acc=%d: %r",
                                     row.account_id, exc)
                    except Exception as exc:
                        _log.warning("autoeval pending acc=%d: %r",
                                     row.account_id, exc)
                    await asyncio.sleep(0.4)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning("autoeval pending loop: %r", exc)


# ------------------------------------------------------------- supervisor

def _wire_events(sio, account_id: int) -> None:
    """Реєструємо хендлери подій. ЛИШЕ async def: python-socketio
    перевіряє inspect.iscoroutinefunction і СИНХРОННІ handler'и викликає
    без await - корутина з лямбди «ніколи не очікується» (RuntimeWarning),
    статус не оновлюється і join_room не висилається → вічне
    «Підключається…» у сайті. Цю помилку ловив live-пробник."""
    async def _evt_connect(*_a: object) -> None:
        await _on_connect(sio, account_id)

    async def _evt_disconnect(*a: object) -> None:
        await _on_disconnect(account_id, *a)

    async def _evt_notification(*_a: object) -> None:
        await _on_event(account_id, "notification")

    async def _evt_list(*_a: object) -> None:
        await _on_event(account_id, "list")

    async def _evt_counter(*_a: object) -> None:
        await _on_event(account_id, "counter")

    async def _evt_handler(payload: object) -> None:
        await _on_handler(account_id,
                          payload if isinstance(payload, dict) else {})

    async def _evt_connect_error(data: object) -> None:
        _st(account_id, connected=False, last_error=str(data)[:200])

    sio.on("connect", _evt_connect)
    sio.on("disconnect", _evt_disconnect)
    sio.on("socket_notification", _evt_notification)
    sio.on("socket_notification_list", _evt_list)
    sio.on("socket_notification_counter", _evt_counter)
    sio.on("socket_notification_handler", _evt_handler)
    sio.on("connect_error", _evt_connect_error)


async def _supervisor(account_id: int) -> None:
    """Життя одного з'єднання: конект зі СВІЖИМ токеном → слухаємо до
    дисконекту → пауза → знову (reconnection=False, реконект під нашим
    контролем - токен між реконектами оновлюється)."""
    backoff = 2.0
    while not _stopping:
        sio = None
        db = SessionLocal()
        try:
            acc = db.get(MystatAccount, account_id)
            if acc is None:
                _log.info("socket: акаунт %d зник - зупиняю", account_id)
                return
            scfg = (db.query(SocketAccountConfig)
                    .filter(SocketAccountConfig.account_id == account_id)
                    .first())
            if scfg is None or not scfg.socket_enabled:
                _log.info("socket: акаунт %d вимкнено в налаштуваннях",
                          account_id)
                return
            token = await _fresh_token(acc)
            db.commit()
        except _PermanentSkip as exc:
            _st(account_id, connected=False, last_error=str(exc))
            _log.warning("socket: акаунт %d не підключається: %s",
                         account_id, exc)
            return
        except ms.MystatError as exc:
            _st(account_id, connected=False, last_error=str(exc))
            _log.warning("socket: mapi недоступний (%r) - retry %0.0fs",
                         exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
            continue
        except Exception as exc:
            _st(account_id, connected=False, last_error=repr(exc))
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
            continue
        finally:
            db.close()

        try:
            sio = socketio.AsyncClient(
                reconnection=False, logger=False, engineio_logger=False)
            _wire_events(sio, account_id)

            db = SessionLocal()
            try:
                acc = db.get(MystatAccount, account_id)
                alias = (acc.branch_alias if acc else "") or "pl"
            finally:
                db.close()
            # AsyncClient не має kwarg `query` (це синхронний клієнт):
            # query-параметри передаються в URL (?alias=ua). socketio_path
            # без слеша - engineio склеює його з path бази сам.
            connect_url = f"{NOTIFY_URL}/?{urlencode({'alias': alias})}"
            await asyncio.wait_for(
                sio.connect(
                    connect_url,
                    headers=NGROK_HEADER,
                    auth={"token": token},
                    socketio_path="socket.io",
                    transports=["websocket", "polling"],
                ),
                timeout=25)
            backoff = 2.0
            # живемо поки з'єднання не впаде
            while sio.connected and not _stopping:
                await asyncio.sleep(1.0)
            # чистий дисконект (сервер закрив) - пауза перед реконектом,
            # щоб фапання сервера не оберталось у гарячий цикл
            if sio.connected is False and not _stopping:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _st(account_id, connected=False, last_error=repr(exc))
            _log.warning("socket: акаунт %d: %r - retry %0.0fs",
                         account_id, exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
        finally:
            if sio is not None:
                try:
                    await sio.disconnect()
                except Exception:
                    pass


# ------------------------------------------------------------------ API

def start_account(account_id: int) -> None:
    """Увімкнути сокет-з'єднання акаунта (idempotent)."""
    if socketio is None:
        _log.warning("socket: python-socketio не встановлено - вимкнено "
                     "(pip install -r requirements.txt)")
        return
    if account_id in _tasks and not _tasks[account_id].done():
        return
    _tasks[account_id] = asyncio.create_task(
        _supervisor(account_id), name=f"socket-{account_id}")


def stop_account(account_id: int) -> None:
    t = _tasks.pop(account_id, None)
    if t is not None:
        t.cancel()
    _status.pop(account_id, None)


async def start_all() -> None:
    """lifespan: підняти всі увімкнені конфіги (+ loop відкладених оцінок)."""
    global _stopping, _pending_loop
    _stopping = False
    if socketio is None:
        return
    db = SessionLocal()
    try:
        ids = [r.account_id for r in
               db.query(SocketAccountConfig)
               .filter(SocketAccountConfig.socket_enabled.is_(True)).all()]
    finally:
        db.close()
    for account_id in ids:
        start_account(account_id)
    if _pending_loop is None or _pending_loop.done():
        _pending_loop = asyncio.create_task(_process_pending_loop(),
                                            name="autoeval-pending")
    if ids:
        _log.info("socket: піднято %d з'єднань", len(ids))


async def stop_all() -> None:
    global _stopping, _pending_loop
    _stopping = True
    for account_id in list(_tasks.keys()):
        stop_account(account_id)
    if _pending_loop is not None:
        _pending_loop.cancel()
        _pending_loop = None


def restart_account(account_id: int, enabled: bool) -> None:
    """Зміна налаштувань з сайту: вмикати/вимикати негайно."""
    if enabled:
        start_account(account_id)
    else:
        stop_account(account_id)
