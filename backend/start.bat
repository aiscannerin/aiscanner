@echo off
title Stop Hunter Pro - Backend

cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Run: python -m venv venv
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

if not exist ".env" (
    echo [WARNING] .env file not found. Copy .env.example to .env and configure it.
    pause
    exit /b 1
)

set FLASK_APP=run.py
set FLASK_ENV=development

echo.
echo  ========================================
echo   Stop Hunter Pro - Backend Starting...
echo  ========================================
echo.

python run.py

pause
