@echo off
rem ============================================================
rem  install_playwright.cmd  -  Stop Hunter Pro
rem  Installs Playwright and Chromium into the backend venv.
rem
rem  Run this once on a new server after:
rem    1. git pull
rem    2. bootstrap.ps1  (which creates the venv)
rem  ...or any time scans fail with "No module named 'playwright'"
rem ============================================================

setlocal

rem -- Resolve paths from script location
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "VENV_PYTHON=%PROJECT_DIR%\backend\venv\Scripts\python.exe"
set "VENV_ACTIVATE=%PROJECT_DIR%\backend\venv\Scripts\activate.bat"

echo.
echo ============================================================
echo  Stop Hunter Pro - Playwright Installer
echo ============================================================
echo  Project: %PROJECT_DIR%
echo.

rem -- Check venv exists
if not exist "%VENV_PYTHON%" (
    echo ERROR: backend venv not found at:
    echo        %VENV_PYTHON%
    echo.
    echo        Run bootstrap.ps1 first to create the venv.
    echo        Then re-run this script.
    pause
    exit /b 1
)
echo [OK] Venv found: %VENV_PYTHON%
echo.

rem -- Activate venv
call "%VENV_ACTIVATE%"

rem -- Install playwright package into the venv
echo [1/3] Installing playwright into venv...
python -m pip install --upgrade playwright
if errorlevel 1 (
    echo ERROR: pip install playwright failed.
    pause
    exit /b 1
)
echo.

rem -- Install Firefox browser binaries
echo [2/3] Downloading Firefox browser binaries (may take a few minutes)...
python -m playwright install firefox
if errorlevel 1 (
    echo ERROR: Chromium install failed.
    echo        Check internet access or try running as Administrator.
    pause
    exit /b 1
)
echo.

rem -- Smoke test
echo [3/3] Verifying import...
python -c "from playwright.sync_api import sync_playwright; print('playwright import OK')"
if errorlevel 1 (
    echo ERROR: Playwright import test failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Done. Playwright is installed in the backend venv.
echo  You can now run start_servers.cmd normally.
echo ============================================================
echo.
endlocal
pause
