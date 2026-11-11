@echo off
title TransM - Frontend (Vite :5173)
cd /d "%~dp0"
echo ========================================================
echo         TransM - Frontend Dev Server (Vite :5173)
echo ========================================================
echo.
if exist "d:\dev\tools\nodejs" (
    set "PATH=d:\dev\tools\nodejs;%PATH%"
)
echo [*] Starting Vite development server on http://localhost:5173 ...
call npm run dev
pause
