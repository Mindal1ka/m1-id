"""Серверна сторона навантажувального тесту: ASGI-app + мок mapi + замір
серверного часу обробки. Запускається ЧЕРЕЗ CLI uvicorn/granian:

  python -m uvicorn scripts.loadtest_server:app --port 8126
  python -m granian --interface asgi scripts.loadtest_server:app --host 127.0.0.1 --port 8126

Серверний час (p50/p95/avg, усе вікно + останні 5с) пишеться в
backend/_server_stats.txt кожні 5с.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="m1id_loadsrv_")
os.environ.setdefault("M1ID_DB_URL", f"sqlite:///{_tmp}/load.db".replace("\\", "/"))
os.environ.setdefault("M1ID_SECRET_KEY",
                      "load-test-secret-key-0123456789abcdef-0123456789")
os.environ.setdefault("M1ID_EMAIL_MX_CHECK", "false")
os.environ.setdefault("M1ID_DEBUG", "1")

import httpx  # noqa: E402

# rate-limit знімаємо: міряємо стелю сервера, не ліміти
import app.services.ratelimit as _rl  # noqa: E402
from fastapi import Depends  # noqa: E402


async def _noop() -> None:
    return None


_rl.rate_limit = lambda *a, **k: Depends(_noop)
_rl.rate_limit_user = _rl.rate_limit

# мок mapi: правдоподібні розміри та RTT ~3мс
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from loadtest_mapi import install_mapi_mock  # noqa: E402

install_mapi_mock()

from app.main import app  # noqa: E402

SERVER_TIMES: list[float] = []
_STATS_FILE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "_server_stats.txt")


@app.middleware("http")
async def _server_timing(request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    SERVER_TIMES.append(time.perf_counter() - t0)
    return response


def _flush_loop() -> None:
    import statistics

    while True:
        time.sleep(5)
        try:
            lines = ["# час обробки запиту сервером, мс"]
            if SERVER_TIMES:
                s_all = sorted(SERVER_TIMES)
                n = len(s_all)
                recent = SERVER_TIMES[-2000:]
                lines.append(
                    f"ALL n={n} p50={s_all[n // 2] * 1000:.0f} "
                    f"p95={s_all[min(n - 1, int(n * .95))] * 1000:.0f} "
                    f"avg={statistics.fmean(s_all) * 1000:.0f}")
                recent.sort()
                m = len(recent)
                lines.append(
                    f"RECENT(2k) p50={recent[m // 2] * 1000:.0f} "
                    f"p95={recent[min(m - 1, int(m * .95))] * 1000:.0f} "
                    f"avg={statistics.fmean(recent) * 1000:.0f}")
            with open(_STATS_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception:  # noqa: BLE001
            pass


threading.Thread(target=_flush_loop, daemon=True).start()
