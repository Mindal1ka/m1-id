@echo off
rem ── M1 ID backend: запуск дев-сервера на http://127.0.0.1:8080 ──
cd /d %~dp0
rem дев-режим: вмикає dev-ендпоінт link-token, Swagger /docs і гучні попередження
set M1ID_DEBUG=1
rem ДЕМО-дані розкладу (7 уроків «сьогодні», щільний тиждень) — лише дев!
rem У прод-батнику цей прапорець НЕ ставиться: на бойовому сервері демо вимкнено.
set M1ID_DEMO_SCHEDULE=1
if not exist .venv (
    echo [M1 ID] створюю віртуальне оточення...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q --upgrade-strategy only-if-needed
echo.
echo [M1 ID] Swagger UI:  http://127.0.0.1:8080/docs
echo [M1 ID] Health:      http://127.0.0.1:8080/api/health
echo.
rem Granian (Rust HTTP) — той самий сервер, що й у проді; --reload для dev.
rem Якщо granian раптом не встав — fallback на uvicorn (той самий ASGI-app).
python -c "import granian" 2>nul
if not errorlevel 1 (
    python -m granian --interface asgi app.main:app --host 127.0.0.1 --port 8080 --reload --reload-paths app
) else (
    uvicorn app.main:app --reload --reload-dir app --reload-delay 1 --port 8080
)
