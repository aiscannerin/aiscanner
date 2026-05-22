@echo off
rem ============================================================
rem  update_and_restart.cmd  -  Stop Hunter Pro
rem  One-command production update script.
rem
rem  What it does (in order):
rem    1. Stops running servers (ports 3010 and 3000)
rem    2. git pull origin main
rem    3. Aborts and restarts old version if pull fails
rem    4. pip install ONLY if backend\requirements.txt changed
rem    5. npm install ONLY if frontend\package-lock.json changed
rem    6. flask db upgrade  (always - idempotent)
rem    7. Restarts servers
rem    8. Prints a summary with timestamps
rem
rem  Usage:
rem    update_and_restart.cmd
rem
rem  Safe to run from Task Scheduler or a desktop shortcut.
rem ============================================================

setlocal EnableDelayedExpansion

rem -- Resolve project root from script location --------------------------------
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "BACKEND_DIR=%PROJECT_DIR%\backend"
set "FRONTEND_DIR=%PROJECT_DIR%\frontend"
set "LOGFILE=%PROJECT_DIR%\update.log"

rem Record start time
set "START_TIME=%TIME%"

echo.
echo  ============================================================
echo   Stop Hunter Pro - Update and Restart
echo  ============================================================
echo   Project : %PROJECT_DIR%
echo   Started : %DATE% %START_TIME%
echo  ============================================================
echo.

rem Write same header to update log
echo. >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo  Update started: %DATE% %START_TIME% >> "%LOGFILE%"
echo  Project: %PROJECT_DIR% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

rem -- Sanity checks ------------------------------------------------------------
if not exist "%PROJECT_DIR%\.git" (
    echo  [ERROR] .git directory not found. Is this the right project folder?
    echo          Expected: %PROJECT_DIR%\.git
    echo. >> "%LOGFILE%"
    echo  [ERROR] .git directory not found >> "%LOGFILE%"
    pause
    exit /b 1
)

if not exist "%BACKEND_DIR%\venv\Scripts\python.exe" (
    echo  [ERROR] Backend venv missing. Run bootstrap.ps1 first.
    echo  [ERROR] Venv missing >> "%LOGFILE%"
    pause
    exit /b 1
)

where git >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] git is not in PATH. Install Git for Windows.
    echo  [ERROR] git not found in PATH >> "%LOGFILE%"
    pause
    exit /b 1
)

rem -- Step 1: Stop servers -----------------------------------------------------
echo  [Step 1/6] Stopping servers...
echo  [Step 1] Stopping servers >> "%LOGFILE%"
call "%PROJECT_DIR%\stop_servers.cmd"
echo  [Step 1] Done >> "%LOGFILE%"

rem -- Step 2: git pull ---------------------------------------------------------
echo  [Step 2/6] Pulling latest code from GitHub...
echo  [Step 2] git pull >> "%LOGFILE%"

cd /d "%PROJECT_DIR%"

rem Save current HEAD so we can detect which files changed
for /f %%H in ('git rev-parse HEAD 2^>nul') do set "OLD_HEAD=%%H"
if "!OLD_HEAD!"=="" (
    echo  [ERROR] Could not determine current git HEAD. Is this a git repo?
    echo  [ERROR] git rev-parse HEAD failed >> "%LOGFILE%"
    goto :ABORT_AND_RESTART
)
echo         Current HEAD: !OLD_HEAD!
echo  Old HEAD: !OLD_HEAD! >> "%LOGFILE%"

rem Use --rebase to avoid the vim merge-commit prompt when histories diverge
git pull --rebase origin main >> "%LOGFILE%" 2>&1
set "PULL_EXIT=!ERRORLEVEL!"

if !PULL_EXIT! NEQ 0 (
    echo.
    echo  [FATAL] git pull failed ^(exit code !PULL_EXIT!^).
    echo          The server has NOT been updated.
    echo          Restarting the previous version now...
    echo.
    echo  [FATAL] git pull failed ^(exit !PULL_EXIT!^) - restarting old version >> "%LOGFILE%"
    goto :ABORT_AND_RESTART
)

rem Get new HEAD
for /f %%H in ('git rev-parse HEAD 2^>nul') do set "NEW_HEAD=%%H"
echo  [Step 2] Done  New HEAD: !NEW_HEAD! >> "%LOGFILE%"

if "!OLD_HEAD!"=="!NEW_HEAD!" (
    echo         No new commits pulled. Already up to date.
    echo  [INFO] No new commits >> "%LOGFILE%"
) else (
    echo         Updated: !OLD_HEAD:~0,7! -^> !NEW_HEAD:~0,7!
    echo  Updated: !OLD_HEAD:~0,7! to !NEW_HEAD:~0,7! >> "%LOGFILE%"
)

rem -- Step 3: pip install (only if requirements.txt changed) -------------------
echo  [Step 3/6] Checking backend dependencies...
echo  [Step 3] Checking requirements.txt >> "%LOGFILE%"

rem If OLD_HEAD == NEW_HEAD, skip (nothing changed)
if "!OLD_HEAD!"=="!NEW_HEAD!" (
    echo         requirements.txt unchanged - skipping pip install.
    echo  [Step 3] Skipped ^(no new commits^) >> "%LOGFILE%"
    goto :SKIP_PIP
)

git diff --quiet "!OLD_HEAD!" "!NEW_HEAD!" -- backend/requirements.txt >nul 2>&1
if !ERRORLEVEL! EQU 1 (
    echo         requirements.txt changed - running pip install...
    echo  [Step 3] requirements.txt changed - pip install >> "%LOGFILE%"
    cd /d "%BACKEND_DIR%"
    call venv\Scripts\pip.exe install -r requirements.txt >> "%LOGFILE%" 2>&1
    if !ERRORLEVEL! NEQ 0 (
        echo  [WARN] pip install returned an error. Check update.log for details.
        echo  [WARN] pip install error >> "%LOGFILE%"
    ) else (
        echo         pip install complete.
        echo  [Step 3] pip install OK >> "%LOGFILE%"
    )
    cd /d "%PROJECT_DIR%"
) else (
    echo         requirements.txt unchanged - skipping pip install.
    echo  [Step 3] Skipped ^(no change^) >> "%LOGFILE%"
)
:SKIP_PIP

rem -- Step 4: npm install (only if package-lock.json changed) ------------------
echo  [Step 4/6] Checking frontend dependencies...
echo  [Step 4] Checking package-lock.json >> "%LOGFILE%"

if "!OLD_HEAD!"=="!NEW_HEAD!" (
    echo         package-lock.json unchanged - skipping npm install.
    echo  [Step 4] Skipped ^(no new commits^) >> "%LOGFILE%"
    goto :SKIP_NPM
)

git diff --quiet "!OLD_HEAD!" "!NEW_HEAD!" -- frontend/package-lock.json >nul 2>&1
if !ERRORLEVEL! EQU 1 (
    echo         package-lock.json changed - running npm install...
    echo  [Step 4] package-lock.json changed - npm install >> "%LOGFILE%"
    cd /d "%FRONTEND_DIR%"
    npm install >> "%LOGFILE%" 2>&1
    if !ERRORLEVEL! NEQ 0 (
        echo  [WARN] npm install returned an error. Check update.log for details.
        echo  [WARN] npm install error >> "%LOGFILE%"
    ) else (
        echo         npm install complete.
        echo  [Step 4] npm install OK >> "%LOGFILE%"
    )
    cd /d "%PROJECT_DIR%"
) else (
    echo         package-lock.json unchanged - skipping npm install.
    echo  [Step 4] Skipped ^(no change^) >> "%LOGFILE%"
)
:SKIP_NPM

rem -- Step 5: flask db upgrade -------------------------------------------------
echo  [Step 5/6] Running flask db upgrade...
echo  [Step 5] flask db upgrade >> "%LOGFILE%"

cd /d "%BACKEND_DIR%"
call venv\Scripts\activate.bat >nul 2>&1
flask db upgrade >> "%LOGFILE%" 2>&1
set "MIGRATE_EXIT=!ERRORLEVEL!"

if !MIGRATE_EXIT! NEQ 0 (
    echo  [WARN] flask db upgrade returned exit code !MIGRATE_EXIT!.
    echo         This may indicate a migration conflict. Check update.log.
    echo         Proceeding with server restart anyway.
    echo  [WARN] flask db upgrade exit !MIGRATE_EXIT! >> "%LOGFILE%"
) else (
    echo         Migrations OK.
    echo  [Step 5] OK >> "%LOGFILE%"
)
cd /d "%PROJECT_DIR%"

rem -- Step 6: Start servers -----------------------------------------------------
echo  [Step 6/6] Starting servers...
echo  [Step 6] Starting servers >> "%LOGFILE%"
call "%PROJECT_DIR%\start_servers.cmd"
echo  [Step 6] Done >> "%LOGFILE%"

rem -- Success summary ----------------------------------------------------------
echo.
echo  ============================================================
echo   Update Complete
echo  ============================================================
echo   Started  : %DATE% %START_TIME%
echo   Finished : %DATE% %TIME%
if "!OLD_HEAD!"=="!NEW_HEAD!" (
    echo   Commits  : No new commits ^(already up to date^)
) else (
    echo   Commits  : !OLD_HEAD:~0,7! -^> !NEW_HEAD:~0,7!
)
echo   Backend  : http://localhost:3010
echo   Frontend : http://localhost:3000
echo   Log file : %LOGFILE%
echo  ============================================================
echo.
echo  [SUCCESS] %DATE% %TIME% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

endlocal
exit /b 0

rem -- Abort handler: restart old version, then exit with error -----------------
:ABORT_AND_RESTART
echo.
echo  ============================================================
echo   Update FAILED - Restarting previous version
echo  ============================================================
echo.
call "%PROJECT_DIR%\start_servers.cmd"
echo.
echo  [WARN] The servers have been restarted on the PREVIOUS version.
echo         Fix the git pull issue and run update_and_restart.cmd again.
echo         Log file: %LOGFILE%
echo.
echo  [ABORTED] %DATE% %TIME% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
endlocal
exit /b 1
