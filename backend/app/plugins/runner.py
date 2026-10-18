"""Runner плагінів: одноразовий subprocess з жорстким таймаутом (2с).

Windows-safe: setrlimit там не працює, тому ліміт часу — kill процесу,
пам'яті — Job Object (ctypes, best-effort), розміру виводу — читання з
лімітом (при перевищенні процес вбивається), «розуму» — AST-ліміти коду.
Процес запускається з мінімальним середовищем (без токенів/ключів хоста).
Результат плагіна — JSON з діями: data / text / notify / storage.
Після виконання процес МЕРТВИЙ (лямбда-модель, нічого у фоні не живе).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from app.plugins.analyzer import CodePolicyError, analyze
from app.plugins.sanitizer import log_safe
from app.plugins.store import PluginFile, PluginRun, new_session
from app.telegram.logmask import install_masking, sanitize

_log = logging.getLogger("m1id.plugins")
install_masking(_log)

TIMEOUT_S = 2.0
MAX_STORAGE_BYTES = 256 * 1024
MAX_STDOUT_BYTES = 320 * 1024      # воркер сам обмежує результат до 256КБ
MAX_STDERR_BYTES = 16 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
WORKER_MEMORY_BYTES = 512 * 1024 * 1024

_HERE = Path(__file__).resolve().parent


def plugin_code(plugin_id: str) -> str | None:
    db = new_session()
    try:
        row = (db.query(PluginFile)
               .filter(PluginFile.plugin_id == plugin_id,
                       PluginFile.path == "plugin.py")
               .first())
        return row.content if row else None
    finally:
        db.close()


def _worker_env() -> dict:
    """Мінімальне середовище воркера: жодних секретів хоста.
    На Windows потрібні SYSTEMROOT/SystemDrive, інакше Python не стартує."""
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
           "PYTHONDONTWRITEBYTECODE": "1"}
    if os.name == "nt":
        for key in ("SYSTEMROOT", "SystemRoot", "SystemDrive", "WINDIR"):
            if os.environ.get(key):
                env[key] = os.environ[key]
    return env


def _attach_job_limits(proc: subprocess.Popen):
    """Windows: Job Object з ліміт пам'яті процесу + KILL_ON_JOB_CLOSE.
    Best-effort: будь-яка помилка → None (лишаються таймаут і ліміти виводу).
    Повертає handle job-а (закрити після завершення процесу)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount",
                "OtherOperationCount", "ReadTransferCount",
                "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE, wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = EXT()
        # PROCESS_MEMORY (0x100) | KILL_ON_JOB_CLOSE (0x2000)
        info.BasicLimitInformation.LimitFlags = 0x100 | 0x2000
        info.ProcessMemoryLimit = WORKER_MEMORY_BYTES
        # 9 = JobObjectExtendedLimitInformation
        if not k32.SetInformationJobObject(
                job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(job)
            return None
        if not k32.AssignProcessToJobObject(job, int(proc._handle)):
            k32.CloseHandle(job)
            return None
        return job
    except Exception as exc:  # ctypes/WinAPI недоступні — не критично
        _log.debug("job object not applied: %r", exc)
        return None


def _close_job(job) -> None:
    if not job:
        return
    try:
        import ctypes
        ctypes.WinDLL("kernel32").CloseHandle(job)
    except Exception:
        pass


def _pump(stream, sink: bytearray, cap: int, over: threading.Event) -> None:
    """Читає потік до cap байтів; при перевищенні піднімає прапор."""
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            room = cap - len(sink)
            if room > 0:
                sink.extend(chunk[:room])
            if len(chunk) > room:
                over.set()
                return
    except (OSError, ValueError):
        return


def _spawn_worker(request: str) -> tuple[int, str, str, str]:
    """→ (returncode, stdout, stderr, problem). problem != '' якщо
    таймаут / надто великий вивід / помилка запуску."""
    data = request.encode("utf-8")
    if len(data) > MAX_REQUEST_BYTES:
        return -1, "", "", "request_too_large: вхідні дані плагіна завеликі"
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", str(_HERE / "worker_boot.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=_worker_env(), cwd=str(_HERE),
            **kwargs)
    except OSError as exc:
        return -1, "", "", f"spawner error: {exc}"

    job = _attach_job_limits(proc)
    out_buf, err_buf = bytearray(), bytearray()
    over = threading.Event()
    threads = [
        threading.Thread(target=_pump, daemon=True,
                         args=(proc.stdout, out_buf, MAX_STDOUT_BYTES, over)),
        threading.Thread(target=_pump, daemon=True,
                         args=(proc.stderr, err_buf, MAX_STDERR_BYTES, over)),
    ]

    def _feed() -> None:
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    threads.append(threading.Thread(target=_feed, daemon=True))
    for t in threads:
        t.start()

    problem = ""
    deadline = time.monotonic() + TIMEOUT_S
    while proc.poll() is None:
        if over.is_set():
            problem = "output_too_large: вивід плагіна завеликий — процес вбито"
            break
        if time.monotonic() > deadline:
            problem = f"timeout: хук думав довше {TIMEOUT_S}с — процес вбито"
            break
        time.sleep(0.01)
    if problem:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    for t in threads[:2]:
        t.join(timeout=1)
    _close_job(job)  # KILL_ON_JOB_CLOSE дочищає можливі дочірні процеси
    for stream in (proc.stdout, proc.stderr):
        try:
            stream.close()
        except OSError:
            pass
    return (proc.returncode if proc.returncode is not None else -1,
            out_buf.decode("utf-8", "replace").replace("\r\n", "\n"),
            err_buf.decode("utf-8", "replace"), problem)


def run_hook(plugin_id: str, hook: str, args: dict,
             user_id: int, trigger: str, trigger_detail: str = "",
             code: str | None = None) -> dict:
    """Виконати хук у worker-процесі. → {'ok', 'result'?, 'error'?, 'ms'}."""
    t0 = time.monotonic()
    if code is None:
        code = plugin_code(plugin_id)
    if not code:
        return {"ok": False, "error": "plugin_code_missing"}

    # повторна перевірка AST перед КОЖНИМ запуском (код у БД міг змінюватись)
    try:
        analyze(code)
    except CodePolicyError as exc:
        return {"ok": False, "error": f"code policy: {exc}"}

    try:
        request = json.dumps({"code": code, "hook": hook, "args": args},
                             ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": f"args не серіалізуються: {exc}"}
    outcome = ""
    ok = False
    rc, stdout, stderr, problem = _spawn_worker(request)
    if problem:
        outcome = problem

    result: dict = {}
    if not problem:
        marker = "===PLUGIN_RESULT===\n"
        idx = stdout.rfind(marker)
        if idx >= 0:
            try:
                parsed = json.loads(stdout[idx + len(marker):].strip())
                ok = bool(parsed.get("ok"))
                # T3: помилка плагіна може містити PII з payload —
                # логуємо лише після санітизації (email/телефон/ПІБ)
                outcome = log_safe(parsed.get("error") or "", limit=300)
                if ok:
                    result = parsed.get("result") or {}
            except ValueError:
                outcome = "worker повернув пошкоджений JSON"
        else:
            # T3: stderr теж санітизуємо перед записом у PluginRun
            outcome = sanitize(f"worker завершився без результату "
                               f"(rc={rc}): {stderr[-300:]}")

    duration_ms = int((time.monotonic() - t0) * 1000)

    db = new_session()
    try:
        safe_outcome = log_safe(outcome, limit=4000)
        db.add(PluginRun(plugin_id=plugin_id, user_id=user_id,
                         trigger=trigger, trigger_detail=trigger_detail[:96],
                         ok=ok, duration_ms=duration_ms,
                         outcome=safe_outcome))
        db.commit()
    finally:
        db.close()

    resp: dict = {"ok": ok, "duration_ms": duration_ms}
    if ok:
        resp["result"] = result
    else:
        resp["error"] = outcome
    return resp
