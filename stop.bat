@echo off
setlocal
title TransM - Full Stack Stopper

echo ========================================================
echo         TransM - AI Subtitle Studio Stopper
echo ========================================================
echo.

echo [*] Checking Backend on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo [*] Terminating Backend process PID %%a
    taskkill /f /t /pid %%a >nul 2>&1
)

echo [*] Checking Frontend on port 5173...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5173" ^| findstr "LISTENING"') do (
    echo [*] Terminating Frontend process PID %%a
    taskkill /f /t /pid %%a >nul 2>&1
)

echo.
echo ========================================================
echo [OK] TransM services stopped successfully.
echo ========================================================
echo.

pause
endlocal
