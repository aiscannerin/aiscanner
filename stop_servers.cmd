@echo off
rem ============================================================
rem  stop_servers.cmd  -  Stop Hunter Pro
rem  Safely stops backend (port 3010) and frontend (port 3000).
rem
rem  Strategy (two-pass):
rem    Pass 1 - kill by port (the actual Flask / Node processes)
rem    Pass 2 - kill by window title (cleanup orphaned cmd wrappers)
rem
rem  Only kills processes bound to OUR ports.
rem  Does NOT kill unrelated Python/Node/system services.
rem ============================================================

setlocal EnableDelayedExpansion

set "PORT_BACKEND=3010"
set "PORT_FRONTEND=3000"

echo.
echo  [STOP] Stopping Stop Hunter Pro servers...
echo  [STOP] Time: %DATE% %TIME%
echo.

rem -- Pass 1: kill by port (backend) ------------------------------------------
echo  [1/4] Stopping backend  (port %PORT_BACKEND%)...
set "KILLED_BACKEND=0"
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT_BACKEND% "') do (
    if "%%P" NEQ "0" (
        taskkill /PID %%P /F >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo        Killed PID %%P  [port %PORT_BACKEND%]
            set "KILLED_BACKEND=1"
        )
    )
)
if "!KILLED_BACKEND!"=="0" echo        No process found on port %PORT_BACKEND%.

rem -- Pass 1: kill by port (frontend) -----------------------------------------
echo  [2/4] Stopping frontend (port %PORT_FRONTEND%)...
set "KILLED_FRONTEND=0"
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT_FRONTEND% "') do (
    if "%%P" NEQ "0" (
        taskkill /PID %%P /F >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo        Killed PID %%P  [port %PORT_FRONTEND%]
            set "KILLED_FRONTEND=1"
        )
    )
)
if "!KILLED_FRONTEND!"=="0" echo        No process found on port %PORT_FRONTEND%.

rem -- Pass 2: kill orphaned cmd wrapper windows by title ----------------------
echo  [3/4] Closing orphaned console windows...
taskkill /FI "WINDOWTITLE eq SHP-Backend-3010*"  /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq SHP-Frontend-3000*" /F >nul 2>&1

rem -- Confirm ports are free ---------------------------------------------------
echo  [4/4] Waiting for sockets to release...
timeout /t 3 /nobreak >nul

set "STILL_BOUND=0"
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT_BACKEND% "') do set "STILL_BOUND=1"
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT_FRONTEND% "') do set "STILL_BOUND=1"

if "!STILL_BOUND!"=="1" (
    echo.
    echo  [WARN] One or more ports still appear bound. A process may need
    echo         more time to release the socket, or another application
    echo         is using these ports. Check with: netstat -ano ^| findstr ":30"
    echo.
) else (
    echo        Ports %PORT_BACKEND% and %PORT_FRONTEND% are free.
)

echo.
echo  [STOP] Done.
echo.
endlocal
