"""Регресійний тест: транзієнтний збій refresh (503) НЕ має
переводити акаунт у needs_relogin — лише остаточна відмова mapi.
Запуск: python smoke_test_transient.py (з папки backend). Файл лишається
в репозиторії як постійний регресійний тест.
"""
from __future__ import annotations

import json
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="m1id_regress_") if (tempfile := __import__("tempfile")) else None
import os  # noqa: E402

os.environ["M1ID_DB_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["M1ID_SECRET_KEY"] = "regress-secret-key-0123456789abcdef-0123456789"
os.environ["M1ID_TELEGRAM_BOT_TOKEN"] = ''   # бот у smoke-тестах не стартує
os.environ["M1ID_EMAIL_MX_CHECK"] = "false"
os.environ["M1ID_DEBUG"] = "1"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import mystat_client as ms  # noqa: E402

TOK_BAD = "TOK_TRANSIENT_xxxxxxxxxxxxxxxxxxxxxxxxxx"
TOK_GOOD = "TOK_FRESH_yyyyyyyyyyyyyyyyyyyyyyyyyyy"

ME_PAYLOAD = {
    "id": 1, "id_user_storage": 2, "name": "Тест", "username": "u",
    "lang": "uk", "profile": "student", "branch_alias": "pl",
    "user_profiles": {"50": {"4": [{"user_id": 2, "photo": "p", "logbook_id": 1}]}},
}


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "")
    if url.endswith("/mystat/auth/me"):
        # me приймає ТОК_BAD (інакше лінк не пройде), решта гілкових
        # ендпоінтів — ні: емулюємо «токен протух»
        if token in (TOK_BAD, TOK_GOOD):
            return httpx.Response(200, json=ME_PAYLOAD)
        return httpx.Response(401, json=[])
    if url.endswith("/mystat/auth/refresh"):
        # ГОЛОВНЕ: refresh відповідає ТРАНЗІЄНТНОЮ помилкою 503 (не 401!)
        if token == TOK_BAD:
            return httpx.Response(503, json={"error": "upstream hiccup"})
        return httpx.Response(401, json={"error": "cannot_refresh"})
    if "/v1/mystat/pl/" in url:
        if token != TOK_GOOD:
            return httpx.Response(401, json=[])
        return httpx.Response(200, json={"ok": 1})
    return httpx.Response(404, json={})


ms.set_transport(sync=httpx.MockTransport(handler),
                async_=httpx.MockTransport(handler))

passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name} {extra}")


with TestClient(app) as c:
    # реєстрація + лінк токена (у debug-режимі link-token доступний)
    r = client_reg = c.post("/api/auth/register", json={
        "username": "regress1", "password": "password123",
        "email": "regress@example.com"})
    assert r.status_code == 200, r.text
    access = r.json()["data"]["access_token"]
    H = {"Authorization": f"Bearer {access}"}
    r = client = c.post("/api/accounts/link-token", json={"access_token": TOK_BAD},
                        headers={"Authorization": f"Bearer {access}"})
    assert r.status_code == 200, r.text

    # проксі: токен TOK_BAD → 401 → refresh → 503 (транзієнт)
    r = c.get("/api/mystat/v1/mystat/pl/count/page-counters",
              headers={"Authorization": f"Bearer {access}"})
    body = r.json()
    check("transient refresh → 502 (не 500/401)", r.status_code == 502
          and body.get("error", [{}])[0].get("code") == "upstream_unreachable",
          f"status={r.status_code} body={json.dumps(body, ensure_ascii=False)[:160]}")

    r = c.get("/api/accounts", headers=H)
    acc = r.json()["data"][0]
    check("акаунт НЕ позначено needs_relogin після транзієнтного збою",
          acc["status"] == "active", f"status={acc['status']}")

    # а тепер refresh відповідає 401 (остаточна смерть) → needs_relogin
    def handler_401_refresh(request: httpx.Request) -> httpx.Response:
        return handler(request)

    # (уже покрито smoke_test_m2: «безнадійний токен → needs_relogin»)

print("REGRESSION OK" if failed == 0 else "REGRESSION FAILED")
