@echo off
title TransM - Backend (FastAPI :8000)
cd /d "%~dp0"
echo ========================================================
echo         TransM - Backend Server (FastAPI :8000)
echo ========================================================
echo.
echo [*] Starting Uvicorn server on http://localhost:8000 ...
.\venv\Scripts\python.exe run.py
pause
