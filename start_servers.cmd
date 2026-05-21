@echo off
:: ============================================================
::  start_servers.cmd  —  Stop Hunter Pro
::  Starts backend (port 3010) and frontend (port 3000) in
::  separate minimized console windows with log capture.
::
::  Logs written to:
::    backend\logs\backend.log
::    frontend\logs\frontend.log
::
::  Duplicate prevention: aborts if ports already in use.
::  Uses %~dp0 so this script works from any deploy location.
:: ============================================================

setlocal EnableDelayedExpansion

:: ── Resolve project root from script location ────────────────────────────────
set "PROJECT_DIR=%~dp0"
:: Strip trailing backslash
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "BACKEND_DIR=%PROJECT_DIR%\backend"
set "FRONTEND_DIR=%PROJECT_DIR%\frontend"
set "PORT_BACKEND=3010"
set "PORT_FRONTEND=3000"

echo.
echo  [START] Starting Stop Hunter Pro servers...
echo  [START] Project: %PROJECT_DIR%
echo  [START] Time:    %DATE% %TIME%
echo.

:: ── Sanity checks ────────────────────────────────────────────────────────────
if not exist "%BACKEND_DIR%\venv\Scripts\python.exe" (
    echo  [ERROR] Backend venv not found at:
    echo          %BACKEND_DIR%\venv\Scripts\python.exe
    echo          Run bootstrap.ps1 or pip install manually first.
    exit /b 1
)

if not exist "%BACKEND_DIR%\.env" (
    echo  [ERROR] backend\.env not found.
    echo          Copy backend\.env.example to backend\.env and fill in values.
    exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules\vite\bin\vite.js" (
    echo  [ERROR] Frontend node_modules not found.
    echo          Run: cd frontend ^&^& npm install
    exit /b 1
)

:: ── Duplicate prevention: abort if ports already in use ──────────────────────
echo  [1/5] Checking ports are free...
set "PORT_CONFLICT=0"

for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT_BACKEND% "') do (
    echo  [ERROR] Port %PORT_BACKEND% is already in use by PID %%P
    echo         Run stop_servers.cmd first.
    set "PORT_CONFLICT=1"
)
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT_FRONTEND% "') do (
    echo  [ERROR] Port %PORT_FRONTEND% is already in use by PID %%P
    echo         Run stop_servers.cmd first.
    set "PORT_CONFLICT=1"
)
if "!PORT_CONFLICT!"=="1" (
    echo.
    exit /b 1
)
echo        Ports %PORT_BACKEND% and %PORT_FRONTEND% are free.

:: ── Ensure log directories exist ─────────────────────────────────────────────
echo  [2/5] Preparing log directories...
if not exist "%BACKEND_DIR%\logs"  mkdir "%BACKEND_DIR%\logs"
if not exist "%FRONTEND_DIR%\logs" mkdir "%FRONTEND_DIR%\logs"

:: Write session header to logs (append mode — keeps history across restarts)
echo. >> "%BACKEND_DIR%\logs\backend.log"
echo ============================================================ >> "%BACKEND_DIR%\logs\backend.log"
echo  Session started: %DATE% %TIME% >> "%BACKEND_DIR%\logs\backend.log"
echo ============================================================ >> "%BACKEND_DIR%\logs\backend.log"

echo. >> "%FRONTEND_DIR%\logs\frontend.log"
echo ============================================================ >> "%FRONTEND_DIR%\logs\frontend.log"
echo  Session started: %DATE% %TIME% >> "%FRONTEND_DIR%\logs\frontend.log"
echo ============================================================ >> "%FRONTEND_DIR%\logs\frontend.log"

echo        Logs: %BACKEND_DIR%\logs\backend.log
echo        Logs: %FRONTEND_DIR%\logs\frontend.log

:: ── Start backend ─────────────────────────────────────────────────────────────
::  /D sets working dir so relative paths inside the command work correctly.
::  Output is appended to logs\backend.log (both stdout and stderr).
echo  [3/5] Starting backend  (http://localhost:%PORT_BACKEND%)...
start "SHP-Backend-3010" /D "%BACKEND_DIR%" /MIN cmd /c ^
    "call venv\Scripts\activate.bat && python run.py >> logs\backend.log 2>&1"
echo        Backend window started (minimized).

:: ── Wait for Flask to bind ───────────────────────────────────────────────────
echo  [4/5] Waiting for backend to bind...
timeout /t 4 /nobreak >nul

:: Verify backend actually came up
set "BACKEND_UP=0"
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT_BACKEND% "') do (
    set "BACKEND_UP=1"
)
if "!BACKEND_UP!"=="0" (
    echo  [WARN] Backend does not appear to be listening on port %PORT_BACKEND% yet.
    echo         Check logs: %BACKEND_DIR%\logs\backend.log
)

:: ── Start frontend ────────────────────────────────────────────────────────────
echo  [5/5] Starting frontend (http://localhost:%PORT_FRONTEND%)...
start "SHP-Frontend-3000" /D "%FRONTEND_DIR%" /MIN cmd /c ^
    "node node_modules\vite\bin\vite.js >> logs\frontend.log 2>&1"
echo        Frontend window started (minimized).

echo.
echo  ============================================================
echo   Stop Hunter Pro — Running
echo  ============================================================
echo   Backend  : http://localhost:%PORT_BACKEND%
echo   Frontend : http://localhost:%PORT_FRONTEND%
echo   Backend log  : %BACKEND_DIR%\logs\backend.log
echo   Frontend log : %FRONTEND_DIR%\logs\frontend.log
echo  ============================================================
echo.
endlocal
