"""M2 smoke-test: прив'язка MyStat, Sync Engine, проксі, refresh-ланцюжок.

Весь справжній mapi підмінюється httpx.MockTransport — тест офлайновий.
Запуск:  python smoke_test_m2.py   (з папки backend, venv активний)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid

_tmp = tempfile.mkdtemp(prefix="m1id_m2_")
os.environ["M1ID_DB_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["M1ID_SECRET_KEY"] = "test-secret-key-m2-0123456789abcdef-0123456789"
os.environ["M1ID_TELEGRAM_BOT_TOKEN"] = ''   # бот у smoke-тестах не стартує
os.environ["M1ID_EMAIL_MX_CHECK"] = "false"
os.environ["M1ID_DEBUG"] = "1"  # link-token — dev-ендпоінт

from fastapi.testclient import TestClient  # noqa: E402
from app.services import mystat_client as ms  # noqa: E402

VALID_TOKENS = {"TOK_OK_aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
REFRESH_MAP = {"TOK_OLD_bbbbbbbbbbbbbbbbbbbbbbbbbbbb":
               "TOK_OK_aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}

ME_PAYLOAD = {
    # форма як у живому mapi (див. scripts/diag_me.py): пласкі поля
    "id": 111213,
    "id_user_storage": 998877,
    "name": "Тестов Тест",
    "username": "test_user",
    "lang": "uk",
    "profile": "student",
    "branch_alias": "pl",
    "branch_id": 4,
    "project_id": 50,
    "user_profiles": {
        "50": {
            "4": [
                {"user_id": 998877, "photo": "x.png", "logbook_id": 111213}
            ]
        }
    },
}


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    # страховка від регресії: подвійний префікс /v1/v1/ — негайний провал
    if "/v1/v1/" in url:
        return httpx.Response(404, json={"message": "double_v1_prefix_bug"})
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "")

    if url.endswith("/mystat/auth/login"):
        body = json.loads(request.content or b"{}")
        if body.get("password") == "good":
            return httpx.Response(200, json={
                "access_token": "TOK_OK_aaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
        return httpx.Response(401, json=[{"field": "password",
                                          "message": "invalid"}])

    if url.endswith("/mystat/auth/refresh"):
        if token in REFRESH_MAP:
            return httpx.Response(200, json={"access_token": REFRESH_MAP[token]})
        return httpx.Response(401, json={"error": "cannot_refresh"})

    if url.endswith("/mystat/auth/me"):
        if token in VALID_TOKENS:
            return httpx.Response(200, json=ME_PAYLOAD)
        return httpx.Response(401, json=[])

    # гілкові GET-ендпоінти
    if "/v1/mystat/pl/" in url:
        if token not in VALID_TOKENS:
            return httpx.Response(401, json=[])
        headers = {}
        if "homework/list" in url:
            # канонічні Laravel-імена з MYSTAT_API §13 + альтернативне
            headers = {
                "X-Pagination-Current-Page": "1",
                "X-Pagination-Page-count": "7",
                "X-Pagination-Total-Count": "93",
                "X-Pagination-Per-Page": "15",
            }
            # перевіряємо, що X-UserId дійшов (після логіна — обов'язковий)
            if request.headers.get("x-userid") != "998877":
                return httpx.Response(400, json=[{"field": "__all__",
                                                  "message": "no_x_user_id"}])
            return httpx.Response(200, json=[{"id": 1}], headers=headers)
        if "/nonexistent/" in url:
            pass  # впаде нижче в 404
        return httpx.Response(200, json={"echo_path": request.url.path,
                                         "echo_query": dict(request.url.params),
                                         "echo_uid": request.headers.get("x-userid")})

    return httpx.Response(404, json={"error": "no_route"})


import json  # noqa: E402

import httpx  # noqa: E402

ms.set_transport(sync=httpx.MockTransport(handler),
                 async_=httpx.MockTransport(handler))

from app.main import app  # noqa: E402

passed = failed = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))


def wait_sync(client: TestClient, headers: dict, account_id: int,
              timeout_s: float = 15.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st = client.get(f"/api/accounts/{account_id}/sync/status",
                        headers=headers).json()["data"]
        if st.get("status") in ("done", "error"):
            return st
        time.sleep(0.2)
    return st


UNIQ = uuid.uuid4().hex[:10]
with TestClient(app) as c:
    # M1-користувач
    r = c.post("/api/auth/register", json={
        "username": f"m2_{UNIQ}", "password": "SuperSecret1!",
        "email": f"{UNIQ}@example.com"})
    pair = r.json()["data"]
    H = {"Authorization": f"Bearer {pair['access_token']}"}

    check("M1 користувача створено", r.status_code == 200)

    # ---------- link-token ----------
    r = c.post("/api/accounts/link-token", json={
        "access_token": "BAD_TOKEN_xxxxxxxxxxxxxxxxxx"}, headers=H)
    check("невалідний токен → 401 mystat_invalid_credentials",
          r.status_code == 401 and r.json()["error"][0]["code"] == "mystat_invalid_credentials")

    r = c.post("/api/accounts/link-token", json={
        "access_token": "TOK_OK_aaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
        headers=H)
    j = r.json()
    check("link-token → акаунт створено", r.status_code == 200 and j["ok"], str(j))
    acc = j["data"]["account"]
    AID = acc["id"]
    check("профіль розпарсено (fio/branch/ids/photo/lang)",
          acc["fio"] == "Тестов Тест" and acc["branch_alias"] == "pl"
          and acc["logbook_id"] == "111213"
          and acc["id_user_storage"] == "998877"
          and acc["photo_url"] == "x.png", str(acc))

    # повторна прив'язка того самого logbook → не дубль
    r = c.post("/api/accounts/link-token", json={
        "access_token": "TOK_OK_aaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
        headers=H)
    total = len(c.get("/api/accounts", headers=H).json()["data"])
    check("повторний link не створює дубль", total == 1, f"total={total}")

    # ---------- sync engine ----------
    st = wait_sync(c, H, AID)
    check("синк завершився done", st.get("status") == "done", str(st)[:400])
    failed_steps = [s for s in st.get("steps", []) if s["status"] == "failed"]
    check("немає провалених кроків", len(failed_steps) == 0, str(failed_steps))
    check("усі кроки done (план синку)",
          len(st.get("steps", [])) == 24
          and all(s["status"] == "done" for s in st["steps"]),
          str([s['section'] for s in st['steps'] if s['status'] != 'done']))

    r = c.post(f"/api/accounts/{AID}/sync", headers=H)
    check("другий синк під час роботи → 409 (або вже done)",
          r.status_code in (200, 409))

    r = c.get(f"/api/accounts/{AID}/snapshots", headers=H).json()
    sections = {s["section"] for s in r["data"]}
    check("снапшоти збережено (profile, balances...)",
          {"profile", "balances", "homework"} <= sections, str(sections))
    r = c.get(f"/api/accounts/{AID}/snapshots/profile", headers=H).json()
    check("снапшот profile = ME_PAYLOAD",
          r["data"].get("id") == ME_PAYLOAD["id"]
          and r["data"].get("branch_alias") == "pl")

    # ---------- проксі ----------
    # РЕГРЕСІЯ: із заповненим token_expires_at проксі обчислює
    # datetime.now(timezone.utc) (проактивний refresh). Раніше timezone
    # не був імпортований -> NameError -> 500 на ВСІХ /api/mystat для
    # акаунтів із реальним JWT. Мок-токени exp не давали і тест мовчав.
    from datetime import datetime as _dt, timedelta as _td
    from app.db.base import SessionLocal as _SL
    from app.db.models import MystatAccount as _MA
    _db = _SL()
    _db.query(_MA).filter(_MA.id == AID).update(
        {"token_expires_at": _dt.utcnow() + _td(hours=1)})
    _db.commit()
    _db.close()

    r = c.get("/api/mystat/v1/mystat/pl/homework/list?status=3&limit=5", headers=H)
    j = r.json()
    check("проксі homework/list → конверт ok", r.status_code == 200 and j["ok"])
    check("пагінація X-Pagination-* (page_count) → meta.pagination",
          j["meta"]["pagination"].get("page_count") == 7
          and j["meta"]["pagination"]["total_count"] == 93, str(j["meta"]))
    check("branch із профілю збігся зі шляхом",
          j["data"][0]["id"] == 1)

    r = c.get("/api/mystat/v1/mystat/pl/count/page-counters", headers=H).json()
    check("проксі page-counters проходить + X-UserId пішов",
          r["ok"] and "page-counters" in r["data"]["echo_path"]
          and r["data"]["echo_uid"] == "998877", str(r)[:200])

    r = c.get("/api/mystat/v1/nonexistent/route", headers=H)
    check("невідомий маршрут за специ → 404 unknown_endpoint",
          r.status_code == 404 and r.json()["error"][0]["code"] == "unknown_endpoint")

    r = c.get("/api/mystat/v1/mystat/pl/config")
    check("проксі без M1 ID токена → 401 authorization",
          r.status_code == 401 and r.json()["error"][0]["field"] == "authorization")

    # ---------- refresh-ланцюжок на проксі ----------
    from app.core.security import encrypt_secret
    from app.db.base import SessionLocal
    from app.db.models import MystatAccount

    db = SessionLocal()
    acc_row = db.get(MystatAccount, AID)
    acc_row.access_token_enc = encrypt_secret(
        "TOK_OLD_bbbbbbbbbbbbbbbbbbbbbbbbbbbb")  # прострочений
    db.commit()
    db.close()

    r = c.get("/api/mystat/v1/mystat/pl/gaming/get-balances", headers=H)
    j = r.json()
    check("401 → refresh TOK_OLD→TOK_OK → повтор успішний",
          r.status_code == 200 and j["ok"], str(j)[:300])

    db = SessionLocal()
    acc_row = db.get(MystatAccount, AID)
    acc_row.access_token_enc = encrypt_secret(
        "TOTALLY_DEAD_0000000000000000000000")
    db.commit()
    db.close()
    r = c.get("/api/mystat/v1/mystat/pl/gaming/get-balances", headers=H)
    check("безнадійний токен → 401 account_needs_relogin",
          r.status_code == 401
          and r.json()["error"][0]["code"] == "account_needs_relogin")

    # ---------- unlink ----------
    r = c.delete(f"/api/accounts/{AID}", headers=H).json()
    check("unlink → deleted", r["data"]["deleted"] is True)
    r = c.get("/api/accounts", headers=H).json()
    check("акаунтів після unlink немає", len(r["data"]) == 0)

print(f"\nПідсумок M2: {passed} PASS / {failed} FAIL")
sys.exit(1 if failed else 0)
