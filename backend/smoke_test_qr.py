"""Smoke-test входу за QR: start → info/approve → poll (одноразово),
хибний код, відхилення, декод QR з зображення (zxing-cpp).

Запуск:  python smoke_test_qr.py   (з папки backend)
"""
from __future__ import annotations

import base64
import io
import os
import tempfile
import time
import uuid

_tmp = tempfile.mkdtemp(prefix="m1id_test_")
os.environ["M1ID_DB_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["M1ID_SECRET_KEY"] = "test-secret-key-m1-0123456789abcdef-0123456789"
os.environ["M1ID_TELEGRAM_BOT_TOKEN"] = ""
os.environ["M1ID_EMAIL_MX_CHECK"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    passed, failed = (passed + 1, failed) if cond else (passed, failed + 1)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" - {extra}" if extra and not cond else ""))


uniq = f"{int(time.time())}{uuid.uuid4().hex[:6]}"
with TestClient(app) as c:
    r = c.post("/api/auth/register", json={
        "username": f"u_{uniq}", "password": "Passw0rd!x", "email": f"{uniq}@gmail.com"})
    phone = {"Authorization": "Bearer " + r.json()["data"]["access_token"]}

    def start():
        return c.post("/api/auth/qr/start", headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537"}).json()["data"]

    d = start()
    check("start: токен/URL/код", len(d["token"]) == 32 and d["url"].endswith("/qr/" + d["token"]) and len(d["code"]) == 2)
    # QR (той самий URL, PNG-рендер) декодується назад zxing-cpp
    import segno
    import zxingcpp
    from PIL import Image
    from app.services import qr_login as qr
    buf = io.BytesIO()
    segno.make(d["url"], error="h").save(buf, kind="png", scale=8, border=4)
    texts = [x.text for x in zxingcpp.read_barcodes(Image.open(io.BytesIO(buf.getvalue())))]
    check("QR декодується в токен", bool(texts) and qr.extract_token(texts[0]) == d["token"], str(texts))
    check("svg data-uri", d["qr"].startswith("data:image/svg+xml"))

    def poll(dd):
        return c.post("/api/auth/qr/poll", json={"token": dd["token"], "secret": dd["secret"]}).json()["data"]

    check("poll: pending", poll(d)["status"] == "pending")
    check("poll: чужий секрет", c.post("/api/auth/qr/poll", json={"token": d["token"], "secret": "x" * 20}).json()["data"]["status"] == "expired")
    check("info без сесії = 401", c.get("/api/auth/qr/info", params={"token": d["token"]}).status_code == 401)
    info = c.get("/api/auth/qr/info", params={"token": d["token"]}, headers=phone).json()["data"]
    check("info: 3 варіанти, є правильний, Chrome · Windows",
          len(info["options"]) == 3 and d["code"] in info["options"] and info["device"] == "Chrome · Windows", str(info))
    check("approve: хибний код = 403",
          c.post("/api/auth/qr/approve", json={"token": d["token"], "code": next(o for o in info["options"] if o != d["code"])}, headers=phone).status_code == 403)
    check("після хибного коду poll = denied", poll(d)["status"] == "denied")

    d = start()
    check("approve: правильний код", c.post("/api/auth/qr/approve", json={"token": d["token"], "code": d["code"]}, headers=phone).json()["ok"])
    p1 = poll(d)
    check("poll: approved + сесія", p1["status"] == "approved" and p1["pair"]["access_token"])
    me = c.get("/api/auth/me", headers={"Authorization": "Bearer " + p1["pair"]["access_token"]})
    check("нова сесія працює", me.status_code == 200 and me.json()["data"]["username"] == f"u_{uniq}")
    check("poll удруге = consumed, без пари", poll(d)["status"] == "consumed" and poll(d)["pair"] is None)

    d = start()
    check("deny", c.post("/api/auth/qr/deny", json={"token": d["token"]}, headers=phone).json()["data"]["denied"])
    check("poll: denied", poll(d)["status"] == "denied")
    check("approve після deny = 404", c.post("/api/auth/qr/approve", json={"token": d["token"], "code": d["code"]}, headers=phone).status_code == 404)

    check("extract_token з посилання/сміття",
          qr.extract_token("глянь https://m1id.xyz/qr/" + "a" * 32 + " ок") == "a" * 32 and qr.extract_token("hello") is None)

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
