"""Smoke-test: вибір зрізу лідерборда для моніторингу (lb_scope/lb_period),
фальшиві сповіщення на порожніх відповідях mapi, перше побачення нового
зрізу, строкові поля налаштувань TG + автооцінка: 205 Reset Content =
успіх, 422/84222 = 'already'. Без реального Telegram і mapi.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import uuid

_tmp = tempfile.mkdtemp(prefix="m1id_lb_")
os.environ["M1ID_DB_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["M1ID_SECRET_KEY"] = "test-secret-key-lb-0123456789abcdef-0123456789"
os.environ["M1ID_EMAIL_MX_CHECK"] = "false"
os.environ["M1ID_TELEGRAM_BOT_TOKEN"] = ""
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
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" - {extra}" if extra and not cond else ""))


UNIQ = f"{int(time.time())}{uuid.uuid4().hex[:6]}"
USERNAME = f"lbuser_{UNIQ}"
EMAIL = f"{UNIQ}@gmail.com"

sent: list[str] = []


async def _fake_notify(chat_id: int, text: str, kb=None) -> bool:
    """Заглушка віддає True (успіх доставки) — контракт poller._notify:
    стан фіксується ЛИШЕ після успішної відправки."""
    sent.append(text)
    return True


pl._notify = _fake_notify


def lb_payload(gm: list[str] | None, sm: list[str] | None) -> dict:
    """Зрізи group:month і stream:month; None = порожня відповідь mapi."""
    def sect(order: list[str]) -> dict:
        rows = [{"id_stud": uid, "fio_stud": f"Студент {uid}",
                 "position": i + 1, "amount": 100 - i}
                for i, uid in enumerate(order)]
        return {"top": rows, "other": [], "new_students": []}

    def scope_node(order: list[str] | None) -> dict:
        if order is None:
            return {}
        return {"month": sect(order)}

    return {"leader_table": {
                "group": scope_node(gm),
                "stream": scope_node(sm)},
            "leader_points": {
                "group": {"studentPosition": (gm or []).index("u2") + 1
                          if "u2" in (gm or []) else None, "totalCount": 90},
                "stream": {"studentPosition": None, "totalCount": None}}}


with TestClient(app) as c:
    r = c.post("/api/auth/register", json={
        "username": USERNAME, "password": "SuperSecret1!", "email": EMAIL})
    check("register", r.status_code == 200)
    access = r.json()["data"]["access_token"]
    H = {"Authorization": f"Bearer {access}"}

    db = SessionLocal()
    user = db.query(User).filter(User.username == USERNAME).first()
    acc = MystatAccount(user_id=user.id, user_seq=1, label="Тест",
                        status="active", id_user_storage="u2",
                        logbook_id="14546", mystat_login="login_lb")
    db.add(acc)
    db.flush()
    link = TelegramLink(user_id=user.id, chat_id=777000222,
                        bot_username="M1_IDBOT")
    db.add(link)
    cfg = TelegramAccountConfig(account_id=acc.id, user_id=user.id,
                                chat_id=777000222)
    db.add(cfg)
    db.commit()
    acc_id = acc.id
    db.close()

    # ---------- строкові поля налаштувань (вибір зрізу) ----------
    r = c.post("/api/telegram/settings", headers=H, json={
        "account_seq": 1, "leaderboard_scope": "group",
        "leaderboard_period": "month"})
    j = r.json()
    check("settings: scope/period прийнято",
          r.status_code == 200
          and j["data"]["leaderboard_scope"] == "group"
          and j["data"]["leaderboard_period"] == "month", str(j))
    r = c.post("/api/telegram/settings", headers=H, json={
        "account_seq": 1, "leaderboard_scope": ""})
    check("settings: '' = усі зрізи",
          r.status_code == 200
          and r.json()["data"]["leaderboard_scope"] == "")

    db = SessionLocal()
    acc = db.get(MystatAccount, acc_id)
    cfg = (db.query(TelegramAccountConfig)
           .filter(TelegramAccountConfig.account_id == acc_id).first())

    # калібровка (перший цикл - запам'ятати, не спамити)
    sent.clear()
    asyncio.run(pl._detect_leaderboard(db, cfg, acc, lb_payload(
        ["u1", "u2", "u3"], ["u2", "u1"]), ""))
    check("калібровка обох зрізів - тихо", sent == [], str(sent))

    # ---------- ВИБІР ЗРІЗУ: моніторимо лише group:month ----------
    cfg.lb_scope = "group"
    cfg.lb_period = "month"
    db.commit()

    sent.clear()
    # зміна лише в stream:month (НЕ моніторимо) → тихо
    asyncio.run(pl._detect_leaderboard(db, cfg, acc, lb_payload(
        ["u1", "u2", "u3"], ["u1", "u2", "u3"]), ""))
    check("вибір зрізу: зміна в іншому зрізі → тихо", sent == [], str(sent))

    sent.clear()
    # зміна в group:month → сповіщення, і саме з нього
    asyncio.run(pl._detect_leaderboard(db, cfg, acc, lb_payload(
        ["u2", "u1", "u3"], ["u1", "u2", "u3"]), ""))
    check("вибір зрізу: зміна в обраному зрізі → сповіщення",
          len(sent) == 1, str(sent))

    # вибраний зріз раптом порожній у mapi (мориг) → ключ зникає з orders,
    # вибір відкату не дає фальшивого «все зникло»
    sent.clear()
    asyncio.run(pl._detect_leaderboard(db, cfg, acc, lb_payload(
        None, None), ""))
    check("порожня відповідь mapi → не «лідерборд змінився»",
          sent == [], str(sent))

    # повернення даних після моригу → це новий стан, але порядок той самий
    sent.clear()
    asyncio.run(pl._detect_leaderboard(db, cfg, acc, lb_payload(
        ["u2", "u1", "u3"], ["u1", "u2", "u3"]), ""))
    check("після моригу порядок не змінився → тихо", sent == [], str(sent))

    # ---------- БЕЗ вибору: ловляться зміни в усіх зрізах ----------
    cfg.lb_scope = ""
    cfg.lb_period = ""
    cfg.leaderboard_mine_only = False  # ловимо ЛЮБУ зміну порядку
    db.commit()
    sent.clear()
    asyncio.run(pl._detect_leaderboard(db, cfg, acc, lb_payload(
        ["u2", "u1", "u3"], ["u3", "u2", "u1"]), ""))
    check("без вибору: зміна в stream:month теж сповіщається",
          len(sent) == 1, str(sent))

    # ================= автооцінка: 205 = УСПІХ =================
    evals: list[tuple[object, object]] = []

    async def _fake_notify_eval(acc, row) -> None:
        evals.append((acc.id, row.status))

    async def _fake_token(acc) -> str:
        return "tok"

    ns._notify_eval = _fake_notify_eval
    ns._fresh_token = _fake_token

    class FakeResp:
        def __init__(self, status_code: int, payload=None):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            if self._payload is None:
                raise ValueError("empty body")  # як у 205 No Content
            return self._payload

    calls: list[tuple] = []

    async def _fake_request(method, path, **kw):
        calls.append((method, path, kw.get("json_body")))
        return FakeResp(kw.pop("_status", 205), kw.pop("_payload", None))

    orig_request = ms.request_async

    scfg = SocketAccountConfig(account_id=acc_id, user_id=user.id,
                               socket_enabled=True, auto_eval=True)
    db.add(scfg)
    db.commit()

    # 205 (успіх у живого mapi, тіло порожнє)
    row = AutoEvalLog(account_id=acc_id, lesson_id="2749001", theme="Тема 1",
                      teach_name="Викладач 1", status="pending")
    db.add(row)
    db.commit()

    async def _rate_205():
        async def _req(method, path, **kw):
            calls.append((method, path, kw.get("json_body")))
            return FakeResp(205, None)
        ms.request_async = _req
        try:
            await ns._rate_pending_row(db, acc, row)
        finally:
            ms.request_async = orig_request

    asyncio.run(_rate_205())
    db.refresh(row)
    check("autoeval: 205 Reset Content → status='ok'",
          row.status == "ok" and row.rated_at is not None, row.status)
    check("autoeval: 205 → TG-повідомлення відправлено", len(evals) == 1
          and evals[0][1] == "ok", str(evals))
    check("autoeval: payload як в офіційного клієнта",
          calls and calls[0][2] == {"mark_lesson": 5, "mark_teach": 5,
                                    "comment": "", "id": 2749001},
          str(calls[:1]))

    # 422 / 84222 ALREADY_USED → 'already', БЕЗ повторного TG
    row2 = AutoEvalLog(account_id=acc_id, lesson_id="2749002", theme="Тема 2",
                       teach_name="Викладач 2", status="pending")
    db.add(row2)
    db.commit()
    evals.clear()

    async def _rate_422():
        async def _req(method, path, **kw):
            return FakeResp(422, {"error": True, "code": 84222})
        ms.request_async = _req
        try:
            await ns._rate_pending_row(db, acc, row2)
        finally:
            ms.request_async = orig_request

    asyncio.run(_rate_422())
    db.refresh(row2)
    check("autoeval: 422/84222 → status='already' (не помилка)",
          row2.status == "already" and row2.rated_at is not None, row2.status)
    check("autoeval: 'already' не дWORKує TG-спам", evals == [], str(evals))

    # 423/84223 CLOSED_TODAY → 'closed'
    row3 = AutoEvalLog(account_id=acc_id, lesson_id="2749003",
                       status="pending")
    db.add(row3)
    db.commit()

    async def _rate_closed():
        async def _req(method, path, **kw):
            return FakeResp(422, {"error": True, "code": 84223})
        ms.request_async = _req
        try:
            await ns._rate_pending_row(db, acc, row3)
        finally:
            ms.request_async = orig_request

    asyncio.run(_rate_closed())
    db.refresh(row3)
    check("autoeval: 84223 CLOSED_TODAY → status='closed'",
          row3.status == "closed" and row3.error_code == 84223, row3.status)

    db.close()

print(f"\nІтог LB/автооцінка: {passed} PASS / {failed} FAIL")
sys.exit(1 if failed else 0)
