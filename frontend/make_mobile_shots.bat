@echo off
chcp 65001 >nul
rem Збірка фронту + мобільні кадри для лендінгу (static\landing-shots\m-*.jpg)
cd /d "%~dp0"
echo [1/2] npm run build ...
call npm run build > "%~dp0shots_log.txt" 2>&1
if errorlevel 1 (
  echo BUILD FAILED >> "%~dp0shots_log.txt"
  echo Збірка впала - див. shots_log.txt
  pause
  exit /b 1
)
echo [2/2] node tools\shots.mjs --mobile ...
node tools\shots.mjs --mobile >> "%~dp0shots_log.txt" 2>&1
echo DONE exit=%errorlevel% >> "%~dp0shots_log.txt"
echo Готово - див. shots_log.txt
pause
