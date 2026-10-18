"""Smoke-test «Нотатки» і «Паролі»: CRUD, пошук, шифрування полів у БД,
ізоляція між користувачами, маскування секретів у списку.

Запуск:  python smoke_test_notes.py   (з папки backend, venv активний)
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import uuid

_tmp = tempfile.mkdtemp(prefix="m1id_notes_")
_DB = f"{_tmp}/test.db".replace("\\", "/")
_NOTES_DB = f"{_tmp}/notes.db".replace("\\", "/")
os.environ["M1ID_DB_URL"] = f"sqlite:///{_DB}"
os.environ["M1ID_SECRET_KEY"] = "notes-secret-key-0123456789abcdef-012345"
os.environ["M1ID_TOKEN_ENC_KEY"] = "notes-test-enc-key"
os.environ["M1ID_TELEGRAM_BOT_TOKEN"] = ""
os.environ["M1ID_EMAIL_MX_CHECK"] = "false"
os.environ["M1ID_DEBUG"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILS.append(name)


_UID: dict[str, int] = {}


def register(c: TestClient, tag: str) -> dict:
    u = uuid.uuid4().hex[:8]
    r = c.post("/api/auth/register", json={
        "username": f"{tag}_{u}", "password": "SuperSecret1!",
        "email": f"{u}@example.com"})
    assert r.status_code == 200, r.text
    _UID[tag] = r.json()["data"]["user"]["id"]
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


with TestClient(app) as c:
    A = register(c, "na")
    B = register(c, "nb")

    # ---- нотатки
    r = c.post("/api/notes", headers=A, json={
        "title": "Список покупок", "body": "# Купити\n- **молоко** 100%\n- хліб"})
    check("створення нотатки", r.status_code == 200)
    nid = r.json()["data"]["id"]
    r = c.get("/api/notes", headers=A)
    items = r.json()["data"]["items"]
    check("список містить нотатку", len(items) == 1 and items[0]["id"] == nid)
    check("прев'ю без розмітки", "#" not in items[0]["preview"]
          and "**" not in items[0]["preview"])
    check("пошук за текстом", len(c.get("/api/notes?q=молоко", headers=A)
                                  .json()["data"]["items"]) == 1)
    check("пошук % не є шаблоном", len(c.get("/api/notes?q=%25", headers=A)
                                       .json()["data"]["items"]) == 1)
    check("пошук без збігу", len(c.get("/api/notes?q=zzz", headers=A)
                                 .json()["data"]["items"]) == 0)
    check("чужа нотатка недоступна",
          c.get(f"/api/notes/{nid}", headers=B).status_code == 404)
    check("чужу нотатку не змінити",
          c.put(f"/api/notes/{nid}", headers=B, json={"title": "x"}).status_code == 404)
    r = c.put(f"/api/notes/{nid}", headers=A, json={
        "title": "Покупки", "body": "нове", "pinned": True})
    check("оновлення нотатки", r.status_code == 200
          and r.json()["data"]["pinned"] is True)
    check("видалення нотатки",
          c.delete(f"/api/notes/{nid}", headers=A).status_code == 200
          and c.get("/api/notes", headers=A).json()["data"]["items"] == [])
    check("без токена 401", c.get("/api/notes").status_code == 401)

    # ---- паролі
    SECRET = "S3cr3t-P@ss-XYZ"
    r = c.post("/api/vault", headers=A, json={
        "title": "github.com", "group": "Робота", "fields": [
            {"kind": "login", "label": "Логін", "value": "octocat"},
            {"kind": "password", "label": "Пароль", "value": SECRET},
            {"kind": "email", "label": "Email", "value": "o@example.com"},
            {"kind": "text", "label": "Опис", "value": "основний акаунт"},
        ]})
    check("створення запису", r.status_code == 200)
    ent = r.json()["data"]
    eid = ent["id"]
    check("відповідь створення містить пароль",
          any(f["value"] == SECRET for f in ent["fields"]))
    ids = [f["id"] for f in ent["fields"]]
    check("поля отримали унікальні id", len(set(ids)) == 4 and all(ids))

    lst = c.get("/api/vault", headers=A).json()["data"]["items"]
    pw = next(f for f in lst[0]["fields"] if f["kind"] == "password")
    check("список маскує пароль", pw["value"] == "" and pw["has_value"] is True)
    check("список віддає логін", any(f["value"] == "octocat" for f in lst[0]["fields"]))

    full = c.get(f"/api/vault/{eid}", headers=A).json()["data"]
    check("повний запис містить пароль",
          any(f["value"] == SECRET for f in full["fields"]))
    check("чужий запис недоступний",
          c.get(f"/api/vault/{eid}", headers=B).status_code == 404)
    check("чужий список порожній",
          c.get("/api/vault", headers=B).json()["data"]["items"] == [])

    # шифрування: у файлі БД пароля й логіна у відкритому вигляді немає
    con = sqlite3.connect(_NOTES_DB)
    row = con.execute("select title, grp, fields_enc from vault_entries").fetchone()
    con.close()
    con = sqlite3.connect(_DB)
    in_main = [r[0] for r in con.execute(
        "select name from sqlite_master where name in ('notes','vault_entries')")]
    con.close()
    check("нотатки/паролі лежать у notes.db, не в m1id.db", in_main == [])
    check("назва лишається відкритою", row[0] == "github.com")
    check("поля зашифровані (немає пароля й логіна)",
          SECRET not in row[2] and "octocat" not in row[2] and row[2] != "")

    # перестановка полів зберігається
    rev = list(reversed(full["fields"]))
    r = c.put(f"/api/vault/{eid}", headers=A, json={
        "title": "github.com", "group": "Робота", "pinned": True,
        "fields": [{"id": f["id"], "kind": f["kind"], "label": f["label"],
                    "value": f["value"]} for f in rev]})
    check("оновлення запису", r.status_code == 200)
    again = c.get(f"/api/vault/{eid}", headers=A).json()["data"]
    check("порядок полів зберігся",
          [f["id"] for f in again["fields"]] == [f["id"] for f in rev])
    check("id полів стабільні", again["pinned"] is True)

    check("невідомий тип поля → 422", c.post("/api/vault", headers=A, json={
        "title": "x", "fields": [{"kind": "evil", "value": "1"}]}).status_code == 422)
    check("видалення запису",
          c.delete(f"/api/vault/{eid}", headers=A).status_code == 200
          and c.get("/api/vault", headers=A).json()["data"]["items"] == [])

# ---------------------------------------------------------------- міграція
# Імітуємо «стару» установку: таблиці notes/vault_entries у m1id.db з даними.
# Перший старт після оновлення має перенести їх у notes.db і прибрати зі старої БД.
from app.core.security import encrypt_secret  # noqa: E402
import json  # noqa: E402

uid = _UID["na"]
old_enc = encrypt_secret(json.dumps(
    [{"id": "m1", "kind": "login", "label": "Логін", "value": "old-login"},
     {"id": "m2", "kind": "password", "label": "Пароль", "value": "OLD-PASS-777"}]))
con = sqlite3.connect(_DB)
con.executescript("""
CREATE TABLE notes (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
  title VARCHAR(200), body TEXT, pinned BOOLEAN, created_at DATETIME, updated_at DATETIME);
CREATE TABLE vault_entries (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
  title VARCHAR(200), grp VARCHAR(60), pinned BOOLEAN, fields_enc TEXT,
  created_at DATETIME, updated_at DATETIME);
""")
con.execute("INSERT INTO notes VALUES (101, ?, 'Стара нотатка', 'старий текст', 1, "
            "'2026-10-01 10:00:00', '2026-10-02 11:00:00')", (uid,))
con.execute("INSERT INTO notes VALUES (102, ?, 'Чужа', 'x', 0, "
            "'2026-10-01 10:00:00', '2026-10-01 10:00:00')", (uid + 999,))
con.execute("INSERT INTO vault_entries VALUES (201, ?, 'old.site', 'Архів', 0, ?, "
            "'2026-10-01 10:00:00', '2026-10-01 10:00:00')", (uid, old_enc))
con.commit()
con.close()

with TestClient(app) as c:
    lst = c.get("/api/notes", headers=A).json()["data"]["items"]
    check("міграція: стара нотатка видна власнику",
          any(n["id"] == 101 and n["title"] == "Стара нотатка" and n["pinned"] for n in lst))
    check("міграція: чужа нотатка не видна", all(n["id"] != 102 for n in lst))
    vl = c.get("/api/vault", headers=A).json()["data"]["items"]
    check("міграція: запис паролів видно", any(e["id"] == 201 and e["group"] == "Архів" for e in vl))
    full = c.get("/api/vault/201", headers=A).json()["data"]
    check("міграція: пароль розшифровується",
          any(f["value"] == "OLD-PASS-777" for f in full["fields"]) and not full["broken"])
    check("після міграції можна створювати нові (id не конфліктують)",
          c.post("/api/notes", headers=A, json={"title": "n"}).status_code == 200)

con = sqlite3.connect(_DB)
left = [r[0] for r in con.execute(
    "select name from sqlite_master where name in ('notes','vault_entries')")]
con.close()
check("міграція: старі таблиці видалено з m1id.db", left == [])

con = sqlite3.connect(_NOTES_DB)
cnt = con.execute("select count(*) from notes where id in (101,102)").fetchone()[0]
con.close()
check("міграція: обидві старі нотатки лежать у notes.db", cnt == 2)

# повторний старт нічого не ламає й не дублює
with TestClient(app) as c:
    lst = c.get("/api/notes", headers=A).json()["data"]["items"]
    check("другий старт: без дублів", sum(1 for n in lst if n["id"] == 101) == 1)

print()
if FAILS:
    print(f"ПРОВАЛЕНО: {len(FAILS)}")
    sys.exit(1)
print("ВСІ ПЕРЕВІРКИ ПРОЙДЕНО")
