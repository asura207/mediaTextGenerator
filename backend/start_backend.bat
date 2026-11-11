@echo off
chcp 65001 >nul
title TransM - Backend (FastAPI :8000)
cd /d "%~dp0"
echo ========================================================
echo         TransM - Backend Server (FastAPI :8000)
echo ========================================================
echo.
echo [*] Starting Uvicorn server on http://localhost:8000 ...
if exist ".\venv\Scripts\python.exe" (
    .\venv\Scripts\python.exe run.py
) else (
    python run.py
)
pause
