"""Smoke: права доступу плагінів (власник/адмін/верифікація/link-токен),
перетин дозволів, фільтр payload подій, unredact, storage-merge, ліміт тіла.
Без мережі і Telegram. Запуск: python smoke_test_plugin_access.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

_tmp = tempfile.mkdtemp(prefix="m1id_plg_acc_")
os.environ.update({
    "M1ID_DB_URL": f"sqlite:///{_tmp}/t.db".replace("\\", "/"),
    "M1ID_SECRET_KEY": "plg-acc-0123456789abcdef0123456789abcdef",
    "M1ID_ADMIN_USER_IDS": "900",
})
sys.path.insert(0, str(Path(__file__).parent))

from app.core.responses import ApiError  # noqa: E402
from app.plugins import events, service  # noqa: E402
from app.plugins import manifest as mf  # noqa: E402
from app.plugins.sanitizer import Redactor  # noqa: E402
from app.plugins.store import (NotifyOutbox, PluginInstall, PluginMeta,  # noqa: E402
                               init_plugin_db, new_session)
from app.routers import plugins as rp  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} - {detail}")


def api_status(coro):
    try:
        asyncio.run(coro)
        return 200
    except ApiError as exc:
        return exc.status_code


init_plugin_db()
alice = SimpleNamespace(id=10, username="alice", username_lower="alice")
bob = SimpleNamespace(id=11, username="bob", username_lower="bob")
admin = SimpleNamespace(id=900, username="root", username_lower="root")

print("== admin з конфігу (без неявного id=1) ==")
check("id=1 не адмін", not rp._is_admin(SimpleNamespace(
    id=1, username="x", username_lower="x")))
check("id з конфігу - адмін", rp._is_admin(admin))

print("== маніфест: сміття -> ManifestError ==")
base = {"id": "acc-test", "name": "A", "version": "1.0.0",
        "permissions": ["storage"]}
for label, patch in {
    "tg_buttons не об'єкти": {"tg_buttons": ["x"]},
    "tg_buttons None": {"tg_buttons": [None]},
    "permissions нехешовані": {"permissions": [[1]]},
    "id з \\n": {"id": "abc\n"},
    "version не рядок": {"version": 1},
    "settings_schema сміття": {"settings_schema": ["x"]},
}.items():
    try:
        mf.validate({**base, **patch})
        check(f"reject {label}", False)
    except mf.ManifestError:
        check(f"reject {label}", True)
    except Exception as exc:  # TypeError/AttributeError = 500
        check(f"reject {label}", False, repr(exc))

print("== ліміт тіла до парсингу ==")


class FakeReq:
    def __init__(self, chunks, cl=None):
        self.headers = {"content-length": cl} if cl else {}
        self._chunks = chunks

    async def stream(self):
        for c in self._chunks:
            yield c


big = [b"x" * 100_000] * 6
try:
    asyncio.run(rp._read_json_body(FakeReq(big)))
    check("chunked >512KB -> 413", False)
except ApiError as exc:
    check("chunked >512KB -> 413", exc.status_code == 413)
try:
    asyncio.run(rp._read_json_body(FakeReq([b"[1]"])))
    check("не-об'єкт JSON -> 422", False)
except ApiError as exc:
    check("не-об'єкт JSON -> 422", exc.status_code == 422)

print("== _store_plugin: власність, ре-аплоад ==")
CODE = ("def on_ui(ctx):\n"
        "    return {'data': {'ok': 1}, 'storage': {'k': ctx.get('params', {}).get('v', 1)},\n"
        "            'notify': [{'text': 'hi #T1'}], 'text': 'x #T1'}\n")
MAN = {"id": "acc-test", "name": "Acc", "version": "1.0.0",
       "permissions": ["storage"], "hooks": {"on_ui": True},
       "storage_limit_kb": 1}


def store(user, man, files=None, is_admin=False, verified=False, vis="public",
          binary=frozenset()):
    db = new_session()
    try:
        meta = rp._store_plugin(db, man, files or {"plugin.py": CODE},
                                user.id, verified=verified, visibility=vis,
                                binary=binary, is_admin=is_admin)
        db.commit()
        return meta.id
    finally:
        db.close()


store(alice, MAN)
try:
    store(bob, {**MAN, "version": "1.0.1"})
    check("чужий re-upload заборонено", False)
except ApiError as exc:
    check("чужий re-upload заборонено", exc.status_code == 403)
store(admin, {**MAN, "version": "1.0.1"}, is_admin=True, verified=True)
db = new_session()
meta = db.get(PluginMeta, "acc-test")
check("власник лишився автором після адмін-аплоаду", meta.uploaded_by == 10)
db.close()

print("== файли: base64-кодування ==")
store(alice, {**MAN, "id": "bin-test", "name": "B"},
      {"plugin.py": CODE, "icon.png": "iVBORw0KGgo="},
      binary={"icon.png"})
db = new_session()
from app.plugins.store import PluginFile  # noqa: E402
enc = {f.path: f.encoding for f in db.query(PluginFile).filter_by(
    plugin_id="bin-test")}
check("png має encoding=base64", enc.get("icon.png") == "base64"
      and enc.get("plugin.py") == "utf-8", str(enc))
db.close()
try:
    rp._check_files({"plugin.py": "x"}, {"plugin.py"})
    check("plugin.py не може бути бінарним", False)
except ApiError:
    check("plugin.py не може бути бінарним", True)

print("== інсталяція: верифікація, link-токен, сміття ==")
# acc-test тепер verified (адмін); зробимо окремий unverified link-плагін
store(alice, {**MAN, "id": "link-test", "name": "L"}, vis="link")
db = new_session()
m = db.get(PluginMeta, "link-test")
m.share_token = "tok123"
db.commit()
db.close()
acc = {"accept_permissions": ["storage"]}
check("unverified для чужого -> 403 (спершу видимість: link без токена 404)",
      api_status(rp.install("link-test", dict(acc), bob)) == 404)
check("link з токеном, але unverified -> 403",
      api_status(rp.install("link-test", {**acc, "share_token": "tok123"},
                            bob)) == 403)
check("автор ставить власний unverified", api_status(
    rp.install("link-test", dict(acc), alice)) == 200)
check("accept_permissions сміття -> 400", api_status(
    rp.install("acc-test", {"accept_permissions": "x"}, bob)) == 400)
check("accept_permissions [[1]] -> 400", api_status(
    rp.install("acc-test", {"accept_permissions": [[1]]}, bob)) == 400)
check("verified: bob ставить", api_status(
    rp.install("acc-test", dict(acc), bob)) == 200)
check("ui без інсталяції -> not_installed", asyncio.run(
    service.run_ui_request("acc-test", 12, {})).get("error")
    == "not_installed")

print("== ре-аплоад вимикає інсталяції ==")
store(admin, {**MAN, "version": "1.0.2"}, is_admin=True, verified=True)
db = new_session()
inst = db.query(PluginInstall).filter_by(user_id=11,
                                         plugin_id="acc-test").first()
check("інсталяцію вимкнено й дозволи скинуто",
      inst.enabled is False and inst.accepted_permissions == [])
db.close()
check("enable без повторної згоди -> 409", api_status(
    rp.enable("acc-test", {"enabled": True}, bob)) == 409)
check("повторна згода", api_status(rp.install("acc-test", dict(acc), bob)) == 200)

print("== перетин дозволів у service ==")
# bob прийняв лише storage (notify:telegram у маніфесті нема) - notify ігнор.
MAN2 = {**MAN, "id": "perm-test", "name": "P", "version": "1.0.0",
        "permissions": ["storage", "notify:telegram"]}
store(admin, MAN2, is_admin=True, verified=True)
db = new_session()
db.add(PluginInstall(user_id=11, plugin_id="perm-test", enabled=True,
                     accepted_permissions=["storage"], settings={},
                     storage="{}", account_seqs=[]))
db.commit()
db.close()


async def fake_payload(meta, user_id, acc_seqs=None, perms=None):
    p = service._BlindPayload({"homework": {"items": []}})
    r = Redactor(user_id, meta.id)
    r._to_real["#T1"] = "Марія"
    p.redactor = r
    return p


orig_payload = service._payload_for
service._payload_for = fake_payload
service._chat_id_for = lambda uid: 555
out = asyncio.run(service.run_ui_request("perm-test", 11, {"v": 7}))
check("on_ui ok", out.get("ok"), str(out))
db = new_session()
inst = db.query(PluginInstall).filter_by(user_id=11,
                                         plugin_id="perm-test").first()
check("storage записано (є дозвіл storage)",
      json.loads(inst.storage).get("k") == 7, inst.storage)
check("notify проігноровано без прийнятого notify:telegram",
      db.query(NotifyOutbox).filter_by(plugin_id="perm-test").count() == 0)
db.close()
service._payload_for = orig_payload

print("== unredact виходу плагіна ==")
service._payload_for = fake_payload
out = asyncio.run(service.run_ui_request("perm-test", 11, {"v": 8}))
service._payload_for = orig_payload
# data не містить #T1, перевіряємо через _run_and_apply напряму
resp = asyncio.run(service._run_and_apply(
    "perm-test", 11, "on_ui", "ui", "t", {"params": {}},
    redactor=(lambda r: (r._to_real.__setitem__("#T1", "Марія"), r)[1])(
        Redactor(11, "perm-test"))))
check("#T1 -> Марія у text", resp["result"]["text"] == "x Марія",
      str(resp.get("result")))

print("== storage: паралельне злиття ==")


def worker(i):
    service._merge_storage("perm-test", 11, {f"key{i}": i}, 4)


ths = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
[t.start() for t in ths]
[t.join() for t in ths]
db = new_session()
st = json.loads(db.query(PluginInstall).filter_by(
    user_id=11, plugin_id="perm-test").first().storage)
db.close()
check("жодне з 12 злиттів не втрачене",
      all(f"key{i}" in st for i in range(12)), str(sorted(st)))
check("ліміт storage діє", service._merge_storage(
    "perm-test", 11, {"big": "x" * 5000}, 1) is False)

print("== LRU-кеші обмежені ==")
for i in range(service._CACHE_MAX + 50):
    service._last_ui.put(("p", "ui", i, "h"), (0, {}))
check("кеш не росте понад ліміт", len(service._last_ui) == service._CACHE_MAX)
check("params входять у ключ кешу",
      service._ui_key("p", 1, {"a": 1}) != service._ui_key("p", 1, {"a": 2}))

print("== фільтр payload подій за дозволами ==")
payload = {"sections": ["homework", "balances", "schedule_week@2026-01-05"],
           "data": {"homework": {"items": [1]}, "balances": {"x": 1},
                    "schedule_week@2026-01-05": {"d": 1}}}
f = events.filter_payload_for("data.fresh", payload, ["homework:read"])
check("лише homework", list(f["data"]) == ["homework"]
      and f["sections"] == ["homework"], str(f))
f = events.filter_payload_for("data.fresh", payload, ["schedule:read"])
check("schedule_week@дата -> дозвіл schedule:read",
      list(f["data"]) == ["schedule_week@2026-01-05"], str(f))
check("без відповідних дозволів -> не доставляти",
      events.filter_payload_for("data.fresh", payload, ["storage"]) is None)
check("deadline_soon без homework:read -> None",
      events.filter_payload_for("homework.deadline_soon",
                                {"items": [1]}, ["storage"]) is None)
check("deadline_soon з homework:read",
      events.filter_payload_for("homework.deadline_soon", {"items": [1]},
                                ["homework:read"]) == {"items": [1]})

print("== плагіни-приклади під новою пісочницею ==")
from app.plugins.analyzer import analyze  # noqa: E402
from app.plugins.runner import run_hook  # noqa: E402
root = Path(__file__).parent.parent / "plugins"
hw = (root / "hw-watch" / "plugin.py").read_text(encoding="utf-8")
sn = (root / "streak-note" / "plugin.py").read_text(encoding="utf-8")
analyze(hw)
analyze(sn)
check("AST приймає hw-watch і streak-note", True)
r = run_hook("hw-watch", "on_event", {
    "event": "homework.deadline_soon", "settings": {"hours_before": "abc",
                                                      "prefix": "<>"},
    "payload": {"items": [{"subject": "<b>M</b>", "title": "T",
                           "due": "x", "remaining_h": "5"},
                          "junk", {"remaining_h": None}]}},
    1, "t", code=hw)
check("hw-watch: float-сміття не падає, HTML екранується",
      r.get("ok") and "&lt;b&gt;M" in r["result"]["notify"][0]["text"]
      and "&lt;&gt;" in r["result"]["notify"][0]["text"], str(r))
r = run_hook("hw-watch", "on_ui", {"payload": None, "storage": "{broken"},
             1, "t", code=hw)
check("hw-watch: payload None + пошкоджений storage",
      r.get("ok") and r["result"]["data"]["value"] == 0, str(r))
r = run_hook("hw-watch", "on_ui", {
    "payload": {"homework": {"items": [{"status": 3}, {"status": 2}]}},
    "storage": {"last_day": __import__("datetime").date.today().isoformat(),
                "prev_count": 4}}, 1, "t", code=hw)
check("hw-watch: той самий день -> storage не пишеться",
      r.get("ok") and "storage" not in r["result"]
      and "минулого разу: 4" in r["result"]["data"]["extra"], str(r))
r = run_hook("streak-note", "on_command_notes", {
    "args_text": "<i>x</i>", "storage": {"notes": ["a<b"]}}, 1, "t", code=sn)
check("streak-note: нотатка зберігається", r.get("ok")
      and r["result"]["storage"]["notes"] == ["a<b", "<i>x</i>"], str(r))
r = run_hook("streak-note", "on_command_notes", {
    "args_text": "", "storage": {"notes": ["a<b"]}}, 1, "t", code=sn)
check("streak-note: HTML екранується", "a&lt;b" in r["result"]["text"], str(r))
r = run_hook("streak-note", "on_command_notes", {
    "args_text": "z" * 201, "storage": {}}, 1, "t", code=sn)
check("streak-note: ліміт довжини нотатки", "задовга" in r["result"]["text"])
r = run_hook("streak-note", "on_command_notes", {
    "args_text": "n" * 200, "storage": {"notes": ["q" * 200] * 50}}, 1, "t",
    code=sn)
size = len(json.dumps(r["result"]["storage"], ensure_ascii=False).encode())
check("streak-note: сумарний storage <= 8КБ", size <= 8 * 1024, str(size))

print(f"\n{PASS} PASS / {FAIL} FAIL")
raise SystemExit(1 if FAIL else 0)
