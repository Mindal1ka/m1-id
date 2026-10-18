"""Smoke-test вкладки «Файли»: аплоад (один файл / кілька → zip), токени,
ізоляція користувачів, використання в нотатках, видалення (з fs і без),
вибір активного акаунта. fs itstep підмінений — тест офлайновий.

Запуск:  python smoke_test_notefiles.py   (з папки backend, venv активний)
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import uuid
import zipfile

_tmp = tempfile.mkdtemp(prefix="m1id_files_")
os.environ["M1ID_DB_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["M1ID_SECRET_KEY"] = "files-secret-key-0123456789abcdef-012345"
os.environ["M1ID_TOKEN_ENC_KEY"] = "files-test-enc-key"
os.environ["M1ID_TELEGRAM_BOT_TOKEN"] = ""
os.environ["M1ID_EMAIL_MX_CHECK"] = "false"
os.environ["M1ID_DEBUG"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import SessionLocal  # noqa: E402
from app.db.models import MystatAccount  # noqa: E402
from app.main import app  # noqa: E402
from app.services import links  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILS.append(name)


# ---- підміна fs itstep
UPLOADS: list[dict] = []
DELETED: list[tuple[int, str]] = []
DELETE_WORKS = {"v": True}


async def fake_upload(account, filename, data, content_type):
    UPLOADS.append({"acc": account.user_seq, "name": filename, "data": data,
                    "ct": content_type})
    return f"https://fs1.itstep.org/api/v1/files/KEY{len(UPLOADS):03d}"


async def fake_delete(account, link):
    DELETED.append((account.user_seq, link))
    return DELETE_WORKS["v"]


links.upload_fs_file = fake_upload
links.delete_fs_file = fake_delete


def register(c: TestClient, tag: str):
    u = uuid.uuid4().hex[:8]
    r = c.post("/api/auth/register", json={
        "username": f"{tag}_{u}", "password": "SuperSecret1!",
        "email": f"{u}@example.com"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    return {"Authorization": f"Bearer {d['access_token']}"}, d["user"]["id"]


def add_account(uid: int, seq: int) -> None:
    db = SessionLocal()
    db.add(MystatAccount(user_id=uid, user_seq=seq, label=f"acc{seq}",
                         branch_alias="pl", id_user_storage="1",
                         access_token_enc="x", language="uk"))
    db.commit()
    db.close()


with TestClient(app) as c:
    A, ua = register(c, "fa")
    B, ub = register(c, "fb")

    r = c.post("/api/files", headers=A, files=[("files", ("a.txt", b"hello", "text/plain"))])
    check("без акаунта MyStat → 404 account_not_found", r.status_code == 404)

    add_account(ua, 1)
    add_account(ua, 2)
    add_account(ub, 1)

    # ---- один файл, активний акаунт №2
    r = c.post("/api/files?__account=2", headers=A,
               files=[("files", ("Конспект.pdf", b"%PDF-1.4 data", "application/pdf"))],
               data={"name": "Мій конспект", "description": "Фізика, тема 3"})
    check("аплоад одного файлу", r.status_code == 200)
    f1 = r.json()["data"]
    tok1 = f1["token"]
    check("токен 16 символів [A-Za-z0-9]", len(tok1) == 16 and tok1.isalnum())
    check("fs отримав файл від активного акаунта №2",
          UPLOADS[-1]["acc"] == 2 and UPLOADS[-1]["name"] == "Конспект.pdf"
          and UPLOADS[-1]["data"] == b"%PDF-1.4 data")
    check("назва/опис/розмір збережено",
          f1["name"] == "Мій конспект" and f1["description"] == "Фізика, тема 3"
          and f1["size"] == 13 and f1["kind"] == "file")
    check("fs-посилання повертається власнику", f1["url"].startswith("https://fs1.itstep.org/"))

    # ---- без ?__account → перший акаунт
    r = c.post("/api/files", headers=A, files=[("files", ("b.png", b"\x89PNG", "image/png"))])
    check("без __account — перший акаунт", r.status_code == 200 and UPLOADS[-1]["acc"] == 1)
    check("назва за замовчуванням = ім'я файлу", r.json()["data"]["name"] == "b.png")

    # ---- кілька файлів → один zip
    r = c.post("/api/files?__account=1", headers=A, files=[
        ("files", ("x.txt", b"one", "text/plain")),
        ("files", ("x.txt", b"two", "text/plain")),
        ("files", ("../../evil.sh", b"rm", "text/plain"))],
        data={"name": "Лабораторні"})
    check("кілька файлів → один запис-zip", r.status_code == 200 and r.json()["data"]["kind"] == "zip")
    z = r.json()["data"]
    check("zip: ім'я, список частин", z["orig_name"] == "Лабораторні.zip"
          and sorted(z["parts"]) == ["evil.sh", "x.txt", "x.txt"])
    zf = zipfile.ZipFile(io.BytesIO(UPLOADS[-1]["data"]))
    names = sorted(zf.namelist())
    check("zip: дублікати перейменовано, zip-slip прибрано",
          names == ["evil.sh", "x (2).txt", "x.txt"])
    check("zip: вміст збережено", zf.read("x.txt") == b"one" and zf.read("x (2).txt") == b"two")

    # ---- валідація
    big = b"0" * (25 * 1024 * 1024 + 1)
    r = c.post("/api/files", headers=A, files=[("files", ("big.bin", big, "application/octet-stream"))])
    check("файл >25 МБ → 413", r.status_code == 413)
    r = c.post("/api/files", headers=A, files=[("files", ("e.txt", b"", "text/plain"))])
    check("порожній файл → 422", r.status_code == 422)
    r = c.post("/api/files", headers=A)
    check("без файлів → 422", r.status_code == 422)
    check("чужий акаунт-seq → 404", c.post("/api/files?__account=9", headers=A,
          files=[("files", ("a.txt", b"x", "text/plain"))]).status_code == 404)

    # ---- ізоляція
    check("список порожній в іншого юзера", c.get("/api/files", headers=B).json()["data"]["items"] == [])
    check("чужий токен → 404", c.get(f"/api/files/{tok1}", headers=B).status_code == 404)
    check("неіснуючий токен → 404 (та сама відповідь)",
          c.get("/api/files/AAAAAAAAAAAAAAAA", headers=B).status_code == 404
          and c.get("/api/files/AAAAAAAAAAAAAAAA", headers=B).json()
          == c.get(f"/api/files/{tok1}", headers=B).json())
    check("сміттєвий токен → 404", c.get("/api/files/..%2f..", headers=B).status_code == 404)
    check("чужий токен не змінити",
          c.put(f"/api/files/{tok1}", headers=B, json={"name": "x"}).status_code == 404)
    check("чужий токен не видалити",
          c.delete(f"/api/files/{tok1}", headers=B).status_code == 404 and not DELETED)
    check("без авторизації 401", c.get("/api/files").status_code == 401)

    # ---- редагування
    r = c.put(f"/api/files/{tok1}", headers=A, json={"name": "Конспект 3", "description": ""})
    check("перейменування", r.status_code == 200 and r.json()["data"]["name"] == "Конспект 3")

    # ---- використання в нотатках
    c.post("/api/notes", headers=A, json={"title": "Фізика",
           "body": f"див. file:{tok1} і ще file:{tok1}\n- [ ] прочитати"})
    c.post("/api/notes", headers=B, json={"title": "Чужа", "body": f"file:{tok1}"})
    lst = c.get("/api/files", headers=A).json()["data"]["items"]
    used = next(x for x in lst if x["token"] == tok1)["notes"]
    check("«використано в» — лише нотатки власника, без дублів",
          len(used) == 1 and used[0]["title"] == "Фізика")
    prev = c.get("/api/notes", headers=A).json()["data"]["items"][0]["preview"]
    check("прев'ю нотатки не світить токен", tok1 not in prev and "📎" in prev)

    # ---- видалення: fs НЕ чіпаємо (FS_DELETE_ENABLED = False)
    r = c.delete(f"/api/files/{tok1}", headers=A)
    check("видалення: запис прибрано, remote_deleted=false",
          r.status_code == 200 and r.json()["data"] == {"deleted": True, "remote_deleted": False})
    check("fs delete НЕ викликався", DELETED == [])
    check("після видалення токен недоступний", c.get(f"/api/files/{tok1}", headers=A).status_code == 404)
    check("нотатка з токеном не зламалась", c.get("/api/notes", headers=A).status_code == 200)

    # ---- прапор увімкнено → видалення на fs знову працює
    from app.routers import notefiles
    notefiles.FS_DELETE_ENABLED = True
    tok2 = next(x for x in c.get("/api/files", headers=A).json()["data"]["items"]
                if x["name"] == "b.png")["token"]
    r = c.delete(f"/api/files/{tok2}", headers=A)
    check("з увімкненим прапором fs delete викликається й підтверджує",
          r.status_code == 200 and r.json()["data"]["remote_deleted"] is True and len(DELETED) == 1)
    notefiles.FS_DELETE_ENABLED = False

print()
if FAILS:
    print(f"ПРОВАЛЕНО: {len(FAILS)}")
    sys.exit(1)
print("ВСІ ПЕРЕВІРКИ ПРОЙДЕНО")
