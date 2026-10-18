"""Smoke-тест «Додаткових»: notify-сокет MyStat + Автооцінювання.

БЕЗ реального з'єднання з сокетом (мережі немає): перевіряємо
API налаштувань, журнали автооцінювання, dedupe, тихі години,
код-мапінг помилок evaluate-lesson і TG-повідомлення про оцінку.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta

_tmp = tempfile.mkdtemp(prefix="m1id_extras_")
os.environ["M1ID_DB_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["M1ID_SECRET_KEY"] = "test-secret-key-extras-0123456789abcdef-0123"
os.environ["M1ID_EMAIL_MX_CHECK"] = "false"
os.environ["M1ID_TELEGRAM_BOT_TOKEN"] = ""  # бот у тесті не стартує
os.environ["M1ID_DEBUG"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import SessionLocal  # noqa: E402
from app.db.models import (  # noqa: E402
    AutoEvalLog,
    MystatAccount,
    SocketAccountConfig,
    TelegramAccountConfig,
    TelegramLink,
    User,
)
from app.services import notify_socket as ns  # noqa: E402
from app.services import mystat_client as ms  # noqa: E402
from app.telegram import poller as pl  # noqa: E402

from app.main import app  # noqa: E402

passed = failed = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" - {extra}" if extra and not cond else ""))


UNIQ = f"{int(time.time())}{uuid.uuid4().hex[:6]}"
USERNAME = f"ex_{UNIQ}"
EMAIL = f"{UNIQ}@gmail.com"
PASSWORD = "SuperSecret1!"

# ── фіктивна доставка TG ──
sent: list[str] = []


async def _fake_notify(chat_id: int, text: str) -> None:
    sent.append(text)


pl._notify = _fake_notify

# ── фіктивний mapi: evaluate-lesson ──
mapi_calls: list[dict] = []
fail_999 = True  # імітація збою mapi для уроку 999 (потім «відновлюється»)


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


_real_request_async = ms.request_async


async def _fake_request_async(method, path, **kwargs):
    mapi_calls.append({"method": method, "path": path, **kwargs})
    if "evaluate-lesson" in path:
        body = kwargs.get("json_body") or {}
        lid = str(body.get("id"))
        if lid == "999" and fail_999:  # мережева аварія → лишається pending
            raise ms.MystatError(503, "upstream_down")
        if lid in ("777", "888"):  # 777 - ALREADY_USED, 888 - CLOSED_TODAY
            code = 84222 if lid == "777" else 84223
            return _FakeResp(409, {"code": code, "message": "err"})
        return _FakeResp(200, {"ok": True})
    return _FakeResp(200, {})


ms.request_async = _fake_request_async

# акаунти в тесті без токенів - підміняємо видачу токена
async def _fake_fresh_token(acc):
    return "fake-token"


ns._fresh_token = _fake_fresh_token

with TestClient(app) as c:
    r = c.post("/api/auth/register", json={
        "username": USERNAME, "password": PASSWORD, "email": EMAIL})
    check("register → ok", r.status_code == 200 and r.json()["ok"] is True)
    access = r.json()["data"]["access_token"]
    H = {"Authorization": f"Bearer {access}"}

    r = c.get("/api/extras/status", headers=H)
    d = r.json()["data"]
    check("status без акаунтів → порожньо, available True",
          r.status_code == 200 and d["accounts"] == []
          and d["available"] is True)

    # ---------- акаунти + TG-прив'язка (для префікса/повідомлень) ----------
    db = SessionLocal()
    user = db.query(User).filter(User.username == USERNAME).first()
    acc1 = MystatAccount(user_id=user.id, user_seq=1, label="Перший",
                         status="active", id_user_storage="u1",
                         mystat_login="ex_login_one", branch_alias="ua")
    acc2 = MystatAccount(user_id=user.id, user_seq=2, label="Другий",
                         status="active", id_user_storage="u2",
                         mystat_login="ex_login_two", branch_alias="ua")
    db.add(acc1)
    db.flush()
    db.add(acc2)
    db.add(TelegramLink(user_id=user.id, chat_id=555000111,
                        bot_username="M1_IDBOT"))
    db.commit()
    acc1_id, acc2_id = acc1.id, acc2.id
    db.close()

    # ---------- налаштування вкладки ----------
    r = c.post("/api/extras/settings", headers=H,
               json={"account_seq": 1, "socket_enabled": True,
                     "auto_eval": True})
    check("settings: сокет + автооцінка для акаунта 1",
          r.status_code == 200
          and r.json()["data"]["socket_enabled"] is True
          and r.json()["data"]["auto_eval"] is True)

    r = c.post("/api/extras/settings", headers=H,
               json={"account_seq": 2, "auto_eval": True})
    check("settings: автооцінка на акаунті 2 сама вмикає сокет",
          r.json()["data"]["socket_enabled"] is True
          and r.json()["data"]["auto_eval"] is True)

    r = c.get("/api/extras/status", headers=H)
    accs = r.json()["data"]["accounts"]
    check("status: конфіги розділені по акаунтах",
          accs[0]["socket_enabled"] is True and accs[1]["socket_enabled"] is True
          and accs[0]["auto_eval"] is True and accs[1]["auto_eval"] is True)
    check("status: не підключено (мережі немає), 0 подій",
          accs[0]["connected"] is False and accs[0]["events"] == 0)

    r = c.post("/api/extras/settings", headers=H,
               json={"account_seq": 2, "socket_enabled": False})
    check("settings: вимкнення сокета працює (автооцінка лишається)",
          r.json()["data"]["socket_enabled"] is False
          and r.json()["data"]["auto_eval"] is True)

    r = c.post("/api/extras/settings", headers=H, json={"account_seq": 9})
    check("settings чужого account_seq → 404",
          r.status_code == 404
          and r.json()["error"][0]["code"] == "account_not_found")

    # ---------- автооцінювання: успіх ----------
    mapi_calls.clear()
    sent.clear()
    asyncio.run(ns._auto_eval(acc1_id, "123", "Тема уроку", "Петренко І."))
    eval_calls = [x for x in mapi_calls if "evaluate-lesson" in x["path"]]
    check("автооцінка: POST /students/evaluate-lesson 5/5 без коментаря",
          len(eval_calls) == 1
          and eval_calls[0]["json_body"] == {"mark_lesson": 5, "mark_teach": 5,
                                             "comment": "", "id": 123}
          and "/v1/mystat/ua/" in eval_calls[0]["path"])
    db = SessionLocal()
    row = (db.query(AutoEvalLog)
           .filter(AutoEvalLog.account_id == acc1_id).first())
    check("автооцінка: журнал → ok",
          row is not None and row.status == "ok"
          and row.rated_at is not None)
    db.close()

    # ---------- TG-повідомлення про оцінку ----------
    db = SessionLocal()
    tcfg = db.query(TelegramAccountConfig).filter(
        TelegramAccountConfig.account_id == acc1_id).first()
    if tcfg is None:
        tcfg = TelegramAccountConfig(account_id=acc1_id, user_id=user.id,
                                     chat_id=555000111)
        db.add(tcfg)
    tcfg.chat_id = 555000111
    tcfg.notify_auto_eval = True
    db.commit()
    db.close()
    sent.clear()
    asyncio.run(ns._auto_eval(acc1_id, "124", "Квести", "Ковальчук О."))
    check("автооцінка: TG-повідомлення з темою і викладачем",
          len(sent) == 1 and "Урок оцінено автоматично" in sent[0]
          and "Квести" in sent[0] and "Петренко" not in sent[0])
    check("автооцінка: сповіщення ПІСЛЯ успішного POST",
          "Оцінка: 5 за урок" in sent[0])

    # ---------- dedupe: та сама подія вдруге → нічого ----------
    mapi_calls.clear()
    sent.clear()
    asyncio.run(ns._auto_eval(acc1_id, "123", "Тема уроку", "Петренко І."))
    check("автооцінка: dedupe по (акаунт, lesson_id)",
          not mapi_calls and not sent)

    # ---------- ALREADY_USED (84222) → теж успіх ----------
    sent.clear()
    tcfg.notify_auto_eval = True
    db = SessionLocal()
    db.query(TelegramAccountConfig).filter(
        TelegramAccountConfig.account_id == acc1_id).update(
        {"notify_auto_eval": True})
    db.commit()
    db.close()
    asyncio.run(ns._auto_eval(acc1_id, "777", "X", "Y"))
    db = SessionLocal()
    row = (db.query(AutoEvalLog)
           .filter(AutoEvalLog.account_id == acc1_id,
                   AutoEvalLog.lesson_id == "777").first())
    check("автооцінка: ALREADY_USED → статус 'already' (оцінка стоїть)",
          row is not None and row.status == "already")
    db.close()

    # ---------- CLOSED_TODAY (84223) → closed ----------
    asyncio.run(ns._auto_eval(acc1_id, "888", "X", "Y"))
    db = SessionLocal()
    row = (db.query(AutoEvalLog)
           .filter(AutoEvalLog.account_id == acc1_id,
                   AutoEvalLog.lesson_id == "888").first())
    check("автооцінка: CLOSED_TODAY → 'closed', код збережено",
          row is not None and row.status == "closed"
          and row.error_code == 84223)
    db.close()

    # ---------- мережева аварія → pending, потім вдається ----------
    asyncio.run(ns._auto_eval(acc1_id, "999", "X", "Y"))
    db = SessionLocal()
    row = (db.query(AutoEvalLog)
           .filter(AutoEvalLog.account_id == acc1_id,
                   AutoEvalLog.lesson_id == "999").first())
    check("автооцінка: збій mapi → урок лишається 'pending'",
          row is not None and row.status == "pending")
    db.close()
    sent.clear()
    db = SessionLocal()
    acc = db.get(MystatAccount, acc1_id)
    row = (db.query(AutoEvalLog)
           .filter(AutoEvalLog.account_id == acc1_id,
                   AutoEvalLog.lesson_id == "999").first())
    fail_999 = False  # mapi «відновився»
    asyncio.run(ns._rate_pending_row(db, acc, row))
    db.close()
    check("автооцінка: pending дорахована після відновлення",
          row.status == "ok" and len(sent) == 1)
    # ---------- автооцінка вимкнена → ігноруємо подію ----------
    db = SessionLocal()
    cfg = (db.query(SocketAccountConfig)
           .filter(SocketAccountConfig.account_id == acc1_id).first())
    cfg.auto_eval = False
    db.commit()
    db.close()
    mapi_calls.clear()
    asyncio.run(ns._auto_eval(acc1_id, "555", "T", "N"))
    check("автооцінка вимкнена → POST не робиться",
          not [x for x in mapi_calls if "evaluate-lesson" in x["path"]])

    # ---------- вимкнений сокет → ігноруємо ----------
    db = SessionLocal()
    cfg.socket_enabled = False
    db.commit()
    db.close()
    asyncio.run(ns._auto_eval(acc1_id, "556", "T", "N"))
    db = SessionLocal()
    n = (db.query(AutoEvalLog)
         .filter(AutoEvalLog.account_id == acc1_id,
                 AutoEvalLog.lesson_id == "556").count())
    check("сокет вимкнений → подія оцінки ігнорується", n == 0)
    db.close()

    # ---------- сокет без auto_eval → fast-path дозволений ----------
    db = SessionLocal()
    cfg2 = (db.query(SocketAccountConfig)
            .filter(SocketAccountConfig.account_id == acc2_id).first())
    check("акаунт 2: конфіг створюється автоматично",
          cfg2 is not None and cfg2.socket_enabled is False)
    db.close()

    # ---------- тихі години: автооцінка відкладається ----------
    db = SessionLocal()
    db.query(SocketAccountConfig).filter(
        SocketAccountConfig.account_id == acc2_id).update(
        {"socket_enabled": True, "auto_eval": True})
    db.commit()
    db.close()
    ns._is_quiet_now = lambda _aid: True
    asyncio.run(ns._auto_eval(acc2_id, "400", "Нічний урок", "Нічний В."))
    db = SessionLocal()
    row = (db.query(AutoEvalLog)
           .filter(AutoEvalLog.account_id == acc2_id,
                   AutoEvalLog.lesson_id == "400").first())
    check("тихі години: урок у черзі pending, без POST",
          row is not None and row.status == "pending"
          and not [x for x in mapi_calls
                   if "evaluate-lesson" in x["path"] and x["id"] == "400"])
    db.close()

    # ---------- ранок: pending обробляється ----------
    ns._is_quiet_now = lambda _aid: False
    db = SessionLocal()
    acc2 = db.get(MystatAccount, acc2_id)
    db.query(SocketAccountConfig).filter(
        SocketAccountConfig.account_id == acc2_id).update(
        {"socket_enabled": True, "auto_eval": True})
    db.commit()
    asyncio.run(ns._rate_pending_row(db, acc2, row))
    db.close()
    check("ранок: відкладений урок оцінено",
          row.status == "ok")

    # ---------- fast-path: refresh_account_now ----------
    refreshed: list[int] = []

    async def _fake_payloads_only(acc, secs):
        refreshed.append(acc.id)

    pl._process_payloads_only = _fake_payloads_only

    async def _fake_process_account(cfg, acc, secs, prefix, plugin_secs=()):
        refreshed.append(("full", acc.id))

    pl._process_account = _fake_process_account

    # без TG-конфіга секцій → тільки снапшоти
    db = SessionLocal()
    db.query(TelegramAccountConfig).filter(
        TelegramAccountConfig.account_id == acc2_id).delete()
    db.commit()
    db.close()
    ns._fastpath_ts[acc2_id] = 0.0
    asyncio.run(ns._on_event(acc2_id, "notification"))
    check("fast-path без TG-конфіга → лише оновлення снапшотів",
          acc2_id in refreshed)

    # тротлінг: друга подія поспіль не дає другого перезапиту
    asyncio.run(ns._on_event(acc2_id, "notification"))
    check("fast-path: тротлінг 120с (серія подій → один перезапит)",
          refreshed.count(acc2_id) == 1)

    # з TG-конфігом → повний прохід детектів
    db = SessionLocal()
    db.add(TelegramAccountConfig(account_id=acc2_id, user_id=user.id,
                                 chat_id=555000111, notify_homework=True))
    db.commit()
    db.close()
    ns._fastpath_ts[acc2_id] = 0.0
    refreshed.clear()
    asyncio.run(ns._on_event(acc2_id, "notification"))
    check("fast-path з TG-конфігом → повний цикл детектів",
          ("full", acc2_id) in refreshed)

    # ---------- хендлер-парсер ----------
    asyncio.run(ns._on_handler(acc2_id, {"handler": "evaluation_notification",
                                         "data": {"evaluation_lesson_id": "601",
                                                  "theme": "T", "teach_name": "N"}}))
    db = SessionLocal()
    n = (db.query(AutoEvalLog)
         .filter(AutoEvalLog.lesson_id == "601").count())
    check("socket_notification_handler → автооцінка за evaluation_lesson_id",
          n == 1)
    db.close()

    ns._fastpath_ts[acc2_id] = 999999999999.0  # тротлінг не заважає
    db = SessionLocal()
    db.query(AutoEvalLog).filter(AutoEvalLog.lesson_id == "602").delete()
    db.commit()
    db.close()
    import json as _json

    asyncio.run(ns._on_handler(acc2_id, {"handler": "evaluation_notification",
                                         "data": _json.dumps(
                                             {"evaluation_lesson_id": "602"})}))
    db = SessionLocal()
    n = (db.query(AutoEvalLog)
         .filter(AutoEvalLog.lesson_id == "602").count())
    check("handler: data JSON-рядком теж парситься", n == 1)
    db.close()

print(f"\nПідсумок Extras: {passed} PASS / {failed} FAIL")
sys.exit(1 if failed else 0)
