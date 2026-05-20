@echo off
title Stop Hunter Pro — Dev Launcher

set ROOT=%~dp0
set BACKEND=%ROOT%backend
set FRONTEND=%ROOT%frontend

echo.
echo  ============================================================
echo   Stop Hunter Pro — Starting Dev Environment
echo  ============================================================
echo.

:: ── Pre-flight checks ──────────────────────────────────────────────────────────
if not exist "%BACKEND%\venv\Scripts\python.exe" (
    echo  [ERROR] Backend venv not found.
    echo          cd backend
    echo          python -m venv venv
    echo          venv\Scripts\pip install -r requirements.txt
    pause & exit /b 1
)

if not exist "%BACKEND%\.env" (
    echo  [ERROR] backend\.env not found.
    echo          Copy backend\.env.example to backend\.env and fill in values.
    pause & exit /b 1
)

if not exist "%FRONTEND%\node_modules\vite\bin\vite.js" (
    echo  [ERROR] Frontend node_modules not installed.
    echo          cd frontend
    echo          npm install
    pause & exit /b 1
)

:: ── Launch backend in new window ───────────────────────────────────────────────
echo  [1/2] Starting Backend  ^(http://localhost:3010^)
start "SHP Backend  :3010" cmd /c "cd /d "%BACKEND%" && call venv\Scripts\activate.bat && set "FLASK_APP=run.py" && set "FLASK_ENV=development" && python run.py & pause"

:: ── Wait for Flask to bind before opening browser ─────────────────────────────
timeout /t 3 /nobreak > nul

:: ── Launch frontend in new window ──────────────────────────────────────────────
echo  [2/2] Starting Frontend ^(http://localhost:3000^)
start "SHP Frontend :3000" cmd /c "cd /d "%FRONTEND%" && node node_modules\vite\bin\vite.js & pause"

echo.
echo  Done. Check the two new windows for server logs.
echo.
pause
