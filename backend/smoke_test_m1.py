"""M1 smoke-test: акаунти M1 ID (реєстрація, вхід, refresh-ротація, me).

Запуск:  python smoke_test_m1.py   (з папки backend, venv активний)
Тест використовує тимчасову БД (env до імпорту застосунку).
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid

_tmp = tempfile.mkdtemp(prefix="m1id_test_")
os.environ["M1ID_DB_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["M1ID_SECRET_KEY"] = "test-secret-key-m1-0123456789abcdef-0123456789"
os.environ["M1ID_TELEGRAM_BOT_TOKEN"] = ''   # бот у smoke-тестах не стартує
os.environ["M1ID_EMAIL_MX_CHECK"] = "true"
# строгий OWASP-режим (grace=0): reuse одразу → ревок усіх. Поведінку
# grace-вікна (паралельні вкладки) покриває smoke_test_refresh_grace.py
os.environ["M1ID_REFRESH_REUSE_GRACE_SECONDS"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

passed = failed = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))


UNIQ = f"{int(time.time())}{uuid.uuid4().hex[:6]}"
USERNAME = f"user_{UNIQ}"
EMAIL = f"{UNIQ}@gmail.com"          # домен з MX — перевірка DNS пройде онлайн
PASSWORD = "SuperSecret1!"

with TestClient(app) as c:
    # ---------- реєстрація ----------
    r = c.post("/api/auth/register", json={
        "username": USERNAME, "password": PASSWORD, "email": EMAIL})
    j = r.json()
    check("register → ok", r.status_code == 200 and j["ok"] is True, str(j))
    data = j.get("data") or {}
    access = data.get("access_token", "")
    refresh1 = data.get("refresh_token", "")
    check("register видає пару токенів + user",
          bool(access) and len(refresh1) == 32 and data["user"]["username"] == USERNAME)
    check("user.email_verified = false", data["user"]["email_verified"] is False)

    # ---------- помилки валідації/унікальності ----------
    r = c.post("/api/auth/register", json={
        "username": USERNAME.lower(), "password": PASSWORD, "email": EMAIL})
    check("дубль username (без урахування регістру) → 409",
          r.status_code == 409 and r.json()["error"][0]["field"] == "username")

    r = c.post("/api/auth/register", json={
        "username": f"x{UNIQ}", "password": PASSWORD,
        "email": EMAIL.replace("@", "+dup@").replace("+dup@", "@x.")})
    # інша скринька того ж домену — має бути email_taken лише якщо збігся; тут просто не 500
    check("реєстрація другого юзера не ламається", r.status_code in (200, 409, 422))

    r = c.post("/api/auth/register", json={
        "username": "ab", "password": PASSWORD, "email": "bad@@mail"})
    check("кривий username/email → 422 конверт",
          r.status_code == 422 and r.json()["ok"] is False)

    r = c.post("/api/auth/register", json={
        "username": f"y{UNIQ}", "password": "short", "email": f"a{UNIQ}@gmail.com"})
    errs = r.json().get("error") or []
    check("слабкий пароль → 422 field=password",
          r.status_code == 422 and any(e["field"] == "password" for e in errs), str(errs))

    r = c.post("/api/auth/register", json={
        "username": f"z{UNIQ}", "password": PASSWORD,
        "email": f"{UNIQ}@no-such-domain-q1w2e3r4.com"})
    codes = [e.get("code") for e in (r.json().get("error") or [])]
    check("неіснуючий домен → помилка DNS",
          r.status_code == 422 and any("domain" in str(x) for x in codes), str(codes))

    # ---------- вхід ----------
    r = c.post("/api/auth/login", json={"login": USERNAME, "password": "WrongPass1!"})
    check("невірний пароль → 401 invalid_credentials",
          r.status_code == 401 and r.json()["error"][0]["code"] == "invalid_credentials")

    r = c.post("/api/auth/login", json={"login": EMAIL, "password": PASSWORD})
    check("вхід за e-mail → ок", r.status_code == 200 and r.json()["ok"] is True)
    refresh2 = r.json()["data"]["refresh_token"]

    r = c.post("/api/auth/login", json={"login": USERNAME.upper(), "password": PASSWORD})
    check("вхід за USERNAME У ВЕРХНЬОМУ регістрі → ок", r.status_code == 200)

    # ---------- me ----------
    r = c.get("/api/auth/me")
    check("me без токена → 401 конверт",
          r.status_code == 401 and r.json()["error"][0]["field"] == "authorization")
    r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
    check("me з токеном → наш користувач",
          r.status_code == 200 and r.json()["data"]["email"] == EMAIL)
    r = c.get("/api/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
    check("me з битим токеном → 401", r.status_code == 401)

    # ---------- refresh-ротація ----------
    r = c.post("/api/auth/refresh", json={"refresh_token": refresh1})
    check("refresh #1 → нова пара", r.status_code == 200
          and r.json()["data"]["refresh_token"] not in ("", refresh1))
    access2 = r.json()["data"]["access_token"]
    refresh3 = r.json()["data"]["refresh_token"]

    r = c.post("/api/auth/refresh", json={"refresh_token": refresh1})
    check("повтор старого refresh (reuse) → 401", r.status_code == 401)

    r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {access2}"})
    check("access з нової пари працює", r.status_code == 200)

    # ---------- logout ----------
    r = c.post("/api/auth/logout", json={"refresh_token": refresh3})
    check("logout → ok", r.status_code == 200 and r.json()["data"]["logged_out"])
    r = c.post("/api/auth/refresh", json={"refresh_token": refresh3})
    check("refresh після logout → 401", r.status_code == 401)
    r = c.post("/api/auth/logout", json={"refresh_token": refresh3})
    check("повторний logout без помилок", r.status_code == 200)

print(f"\nПідсумок M1: {passed} PASS / {failed} FAIL")
sys.exit(1 if failed else 0)
