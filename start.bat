@echo off
title TransM - Full Stack Launcher

echo ========================================================
echo         TransM - AI Subtitle Studio Launcher
echo ========================================================
echo.

if exist "d:\dev\tools\nodejs" (
    set "PATH=d:\dev\tools\nodejs;%PATH%"
)

echo [*] Starting Backend Server (FastAPI on Port 8000)...
start "TransM - Backend API" "%~dp0backend\start_backend.bat"

echo [*] Starting Frontend Server (Vite on Port 5173)...
start "TransM - Frontend Studio" "%~dp0frontend\start_frontend.bat"

echo.
echo ========================================================
echo [OK] Backend and Frontend launched in separate windows!
echo - Web Studio:      http://localhost:5173
echo - Backend API:     http://localhost:8000/docs
echo ========================================================
echo.

ping 127.0.0.1 -n 4 >nul
start http://localhost:5173
