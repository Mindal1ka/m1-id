# -*- coding: utf-8 -*-
"""Smoke: плагін-полер (дані плагінам без ТГ) + on_daily + нові дозволи."""
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="m1id_plgpoll_smoke_")
os.environ.update({
    "M1ID_DB_URL": f"sqlite:///{_tmp}/t.db".replace("\\", "/"),
    "M1ID_PLUGINS_DB_URL": f"sqlite:///{_tmp}/p.db".replace("\\", "/"),
    "M1ID_SECRET_KEY": "smoke-secret",
    "M1ID_SPEC_CACHE": _tmp,
})
sys.path.insert(0, ".")

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}")


# ---------------------------------------------------------------- manifest
from app.plugins import manifest as mf

check("нові дозволи у білому списку",
      all(p in mf.PERMISSIONS for p in
          ["shop:read", "news:read", "payments:read", "clubs:read",
           "progress:read"]))
check("секції за новими дозволами",
      mf.sections_for(["shop:read", "news:read"]) ==
      ["shop_products", "news"])
check("on_daily у KNOWN_HOOKS", "on_daily" in mf.KNOWN_HOOKS)
try:
    mf.validate({"id": "x-test", "name": "X", "version": "1.0.0",
                 "permissions": ["payments:read"], "hooks": {"on_daily": True}})
    check("маніфест з payments:read + on_daily валідний", True)
except mf.ManifestError as e:
    check(f"маніфест з payments:read + on_daily валідний ({e})", False)

# ---------------------------------------------------------------- units
from app.plugins import poller as ppoller
from app.plugins.store import init_plugin_db, new_session, PluginMeta, PluginInstall
import json

init_plugin_db()
db = new_session()
db.add(PluginMeta(id="poll-test", name="Poll", version="1.0.0",
                  author="a", description="d", verified=True,
                  manifest={"permissions": ["homework:read", "shop:read"],
                            "hooks": {"on_event": True}}))
db.add(PluginInstall(user_id=1, plugin_id="poll-test", enabled=True,
                     accepted_permissions=["homework:read", "shop:read"],
                     account_seqs=[2]))
db.add(PluginMeta(id="daily-test", name="Daily", version="1.0.0",
                  author="a", description="d", verified=True,
                  manifest={"permissions": ["homework:read"],
                            "hooks": {"on_daily": True}}))
db.add(PluginInstall(user_id=1, plugin_id="daily-test", enabled=True,
                     accepted_permissions=["homework:read"]))
db.commit()
db.close()

from app.db.base import SessionLocal, init_db
from app.db.models import MystatAccount
init_db()
db = SessionLocal()
from app.db.models import User
db.add(User(id=1, username="tester", username_lower="tester",
             email="t@t.t", password_hash="x"))
db.commit()
db.add(MystatAccount(user_id=1, user_seq=1, mystat_login="acc1", fio="Ф1",
                     access_token_enc="x", status="active"))
db.add(MystatAccount(user_id=1, user_seq=2, mystat_login="acc2", fio="Ф2",
                     access_token_enc="x", status="active"))
db.commit()
db.close()

db = SessionLocal()
try:
    units = ppoller._units()
finally:
    db.close()

check("units знайдено для акаунта seq=2", any(u[1] == 2 for u in units))
check("фільтр account_seqs: seq=1 НЕ в юнітах (плагін лише для seq=2)",
      not any(u[1] == 1 for u in units))
check("секції юніта = homework + shop_products",
      any(set(u[2]) == {"homework", "shop_products"} for u in units))

# ---------------------------------------------------------------- on_daily
import asyncio
from app.plugins import service

fired = {}


async def fake_run(plugin_id, user_id, **kw):
    fired["pid"] = plugin_id
    fired["uid"] = user_id
    fired["hook"] = kw.get("hook")
    return {"ok": True, "result": {}}


_orig = service._run_and_apply
service._run_and_apply = fake_run
_orig_pf = service._payload_for


async def fake_payload(meta, user_id, acc_seqs=None, perms=None):
    return {"homework": {"items": []}}


service._payload_for = fake_payload

asyncio.run(service.dispatch_daily("daily-test", 1))
check("on_daily запустився", fired.get("hook") == "on_daily"
      and fired.get("pid") == "daily-test")

# повторний виклик того ж дня — cooldown блокує
r = asyncio.run(service.dispatch_daily("daily-test", 1))
check("on_daily повторно того ж дня — не запускається (cooldown)",
      r is None)
service._run_and_apply = _orig
service._payload_for = _orig_pf

# ---------------------------------------------------------------- main import
check("app.main імпортується", True)

print(f"\nІтог plugin-poller: {PASS} PASS / {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
