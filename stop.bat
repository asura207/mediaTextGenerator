@echo off
chcp 65001 >nul
setlocal
title TransM - Full Stack Stopper

echo ========================================================
echo         TransM - AI Subtitle Studio Stopper
echo ========================================================
echo.

echo [*] Checking Backend on port 8000...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo [*] Terminating Backend process tree PID %%a
    taskkill /f /t /pid %%a >nul 2>&1
)

echo [*] Checking Frontend on port 5173...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5173" ^| findstr "LISTENING"') do (
    echo [*] Terminating Frontend process tree PID %%a
    taskkill /f /t /pid %%a >nul 2>&1
)

echo [*] Cleaning up TransM console windows and child ffmpeg workers...
taskkill /f /t /fi "WINDOWTITLE eq TransM - Backend*" >nul 2>&1
taskkill /f /t /fi "WINDOWTITLE eq TransM - Frontend*" >nul 2>&1
taskkill /f /im ffmpeg.exe >nul 2>&1

echo.
echo ========================================================
echo [OK] TransM services (Uvicorn, Vite, FFmpeg) stopped cleanly.
echo ========================================================
echo.

pause
endlocal
