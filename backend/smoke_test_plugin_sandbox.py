"""Регресійний тест пісочниці плагінів: усі спроби escape мають бути відхилені.

Два шари перевіряються окремо:
  1) AST-аналізатор (analyze) має відхилити код на аплоаді;
  2) воркер (runtime) має зупинити код, навіть якщо AST-перевірку обійдено
     (код запускається напряму через _spawn_worker, без analyze).
Запуск: python smoke_test_plugin_sandbox.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="m1id_plg_sbx_")
os.environ.update({
    "M1ID_DB_URL": f"sqlite:///{_tmp}/t.db".replace("\\", "/"),
    "M1ID_SECRET_KEY": "plg-sbx-0123456789abcdef0123456789abcdef",
})
sys.path.insert(0, str(Path(__file__).parent))

from app.plugins import analyzer, worker_boot  # noqa: E402
from app.plugins.analyzer import CodePolicyError, analyze  # noqa: E402
from app.plugins.runner import _spawn_worker  # noqa: E402

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} - {detail}")


def wrap(body: str) -> str:
    return "def on_ui(ctx):\n" + "".join(
        "    " + line + "\n" for line in body.strip().splitlines())


# (назва, тіло/код). Кожен має бути відхилений analyze().
AST_ATTACKS = {
    "random._os.system": "import random\nrandom._os.system('echo pwn')",
    "collections._sys": "import collections\nx = collections._sys.modules",
    "string._re / functools._x": "import string\nx = string._re",
    "from random import _os": "from random import _os",
    "import os": "import os",
    "import json.decoder": "import json.decoder",
    "relative import": "from . import x",
    "dunder class": "x = ().__class__",
    "format leak": "x = '{0.__class__}'.format(1)",
    "format leak, no dunder const": "x = 'abc'.format(1)",
    "format_map": "x = 'abc'.format_map({})",
    "mult folding": "x = getattr(1, '_' * 2 + 'class' + '__')",
    "mult folding 2": "x = getattr(1, 'class'.join(['__', '__']))",
    "mod folding": "x = getattr(1, '%s%s' % ('__', 'class__'))",
    "fstring folding": "x = getattr(1, f\"{'__'}class{'__'}\")",
    "gi_frame": "def g():\n    yield 1\nx = g().gi_frame",
    "f_back chain": "def g():\n    yield 1\nx = g().gi_frame.f_back.f_globals",
    "co_ attribute": "x = (lambda: 0).co_code",
    "mro": "x = str.mro()",
    "__builtins__ name": "x = __builtins__",
    "__import__ call": "__import__('os')",
    "eval": "eval('1')",
    "match _attr": "match 1:\n    case int(_x=1):\n        pass",
    "single underscore attr": "import json\nx = json._default_decoder",
}

for name, code in AST_ATTACKS.items():
    try:
        analyze(code)
        check(f"AST rejects: {name}", False, "accepted")
    except CodePolicyError:
        check(f"AST rejects: {name}", True)

print("== legit code still accepted ==")
for name, code in {
    "json/math/random": "import json, math, random\n"
                        "def on_ui(ctx):\n    return {'data': random.random()}",
    "f-string": "def on_ui(ctx):\n    n = 3\n    return {'text': f'n={n}'}",
    "single-underscore name": "def on_ui(ctx):\n    _x = 1\n    return {}",
}.items():
    try:
        analyze(code)
        check(f"accepts: {name}", True)
    except CodePolicyError as exc:
        check(f"accepts: {name}", False, str(exc))

print("== module list in sync ==")
check("ALLOWED_MODULES analyzer == worker",
      analyzer.ALLOWED_MODULES == worker_boot.ALLOWED_MODULES,
      f"{analyzer.ALLOWED_MODULES ^ worker_boot.ALLOWED_MODULES}")
check("denied attrs in sync",
      analyzer.DENIED_ATTRS == worker_boot._DENIED_ATTRS)


def run_raw(code: str, hook: str = "on_ui") -> dict:
    """Запуск воркера МИНАЮЧИ analyze() - перевірка runtime-шару."""
    rc, out, err, problem = _spawn_worker(json.dumps(
        {"code": code, "hook": hook, "args": {"params": {}}}))
    marker = "===PLUGIN_RESULT===\n"
    i = out.rfind(marker)
    if problem:
        return {"ok": False, "error": problem}
    if i < 0:
        return {"ok": False, "error": f"no result rc={rc} {err[-200:]}"}
    return json.loads(out[i + len(marker):])


SECRET = "sandbox-escape-marker"
RUNTIME_ATTACKS = {
    "random._os (direct)": "import random\n" + wrap("return {'data': random._os.getcwd()}"),
    "collections._sys (direct)": "import collections\n" + wrap("return {'data': list(collections._sys.modules)}"),
    "getattr random _os": "import random\n" + wrap("return {'data': getattr(random, '_' + 'os').getcwd()}"),
    "getattr built dunder (mult)": wrap("return {'data': getattr(1, '_' * 2 + 'class' + '__').__name__}"),
    "hasattr private is False": wrap("import random\nreturn {'data': hasattr(random, '_os')}"),
    "json.codecs": "import json\n" + wrap("return {'data': json.codecs.open('worker_boot.py').read()[:50]}"),
    "re.enum / re.functools": "import re\n" + wrap("return {'data': str(re.functools)}"),
    "statistics.sys": "import statistics\n" + wrap("return {'data': str(statistics.sys)}"),
    "format traversal": wrap("return {'data': '{0.__class__}'.format(1)}"),
    "format traversal runtime name": wrap("f = getattr('x', 'for' + 'mat')\nreturn {'data': f('{0.real}', 1)}"),
    "generator frame": wrap("def g():\n    yield 1\nx = g()\nnext(x)\nreturn {'data': str(getattr(x, 'gi_' + 'frame'))}"),
    "from random import _os": "from random import _os\n" + wrap("return {}"),
    "from random import os (not exported)": "from random import os\n" + wrap("return {}"),
    "import os": wrap("import os\nreturn {'data': os.getcwd()}"),
    "import sys": wrap("import sys\nreturn {'data': 1}"),
    "ctx.get dunder": wrap("return {'data': str(ctx.get('__class__'))}"),
    "ctx private data": wrap("return {'data': str(ctx._data)}"),
    "open": wrap("return {'data': open('worker_boot.py').read()}"),
    "__builtins__ lookup": wrap("return {'data': str(__builtins__)}"),
}

print("== worker layer: safe module wrappers (unit) ==")
SM = worker_boot._SAFE_MODULES
for mod, bad in (("random", "_os"), ("random", "os"), ("collections", "_sys"),
                 ("collections", "sys"), ("json", "codecs"),
                 ("json", "decoder"), ("re", "enum"), ("re", "functools"),
                 ("statistics", "sys"), ("statistics", "random"),
                 ("string", "_re"), ("functools", "sys"),
                 ("datetime", "sys")):
    check(f"wrapper {mod} has no {bad}", not hasattr(SM[mod], bad))
check("no module objects inside wrappers", not any(
    type(v).__name__ == "module" for ns in SM.values() for v in vars(ns).values()))
for bad in ("_os", "__class__", "gi_frame", "f_back", "co_code", "format",
            "format_map", "mro"):
    try:
        worker_boot._safe_getattr("x", bad)
        check(f"safe getattr blocks {bad}", False)
    except AttributeError:
        check(f"safe getattr blocks {bad}", True)
check("safe getattr allows normal names",
      worker_boot._safe_getattr("x", "upper")() == "X")
check("safe hasattr hides private", worker_boot._safe_hasattr([], "__len__") is False)

print("== runtime layer (worker, incl. its own AST re-check) ==")
for name, code in RUNTIME_ATTACKS.items():
    resp = run_raw(code)
    data = json.dumps(resp, ensure_ascii=False)
    leaked = resp.get("ok") and name != "hasattr private is False"
    if str(resp.get("error", "")).startswith("no result"):
        leaked = True  # збій харнесу не вважаємо «заблоковано»
    if name == "hasattr private is False":
        leaked = not (resp.get("ok") and resp["result"]["data"] is False)
    check(f"runtime blocks: {name}", not leaked, data[:200])

print("== runtime: safe wrappers work ==")
resp = run_raw("import json, math, random, re, collections, functools, "
               "itertools, string, textwrap, statistics, datetime\n"
               + wrap("c = collections.Counter('aab')\n"
                      "d = datetime.datetime(2024, 1, 2) + datetime.timedelta(days=1)\n"
                      "return {'data': [json.loads('[1]')[0], math.floor(2.5),\n"
                      "  re.sub('a', 'b', 'aa'), c['a'], functools.reduce(lambda a, b: a + b, [1, 2, 3]),\n"
                      "  list(itertools.islice(itertools.count(), 2)), string.digits[:2],\n"
                      "  textwrap.shorten('hello world foo', 8), statistics.mean([1, 3]),\n"
                      "  d.isoformat()[:10], 0 <= random.random() < 1]}"))
check("stdlib wrappers usable", resp.get("ok") and resp["result"]["data"][:5]
      == [1, 2, "bb", 2, 6], json.dumps(resp, ensure_ascii=False)[:300])

print("== runner limits ==")
resp = run_raw(wrap("return {'data': 'x' * (5 * 1024 * 1024)}"))
check("oversized output rejected", not resp.get("ok"), str(resp)[:120])
resp = run_raw(wrap("while True:\n    pass"))
check("infinite loop killed (timeout)", not resp.get("ok")
      and "timeout" in str(resp.get("error")))
env_resp = run_raw(wrap("return {'data': 1}"))
check("worker starts with minimal env", env_resp.get("ok"), str(env_resp))

print(f"\n{PASS} PASS / {FAIL} FAIL")
raise SystemExit(1 if FAIL else 0)
