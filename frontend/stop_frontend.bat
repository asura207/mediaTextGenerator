@echo off
setlocal
title TransM - Stop Frontend (:5173)

echo ========================================================
echo         TransM - Stop Frontend (Vite :5173)
echo ========================================================
echo.

echo [*] Checking Frontend on port 5173...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5173" ^| findstr "LISTENING"') do (
    echo [*] Terminating Frontend process PID %%a
    taskkill /f /t /pid %%a >nul 2>&1
)

echo.
echo ========================================================
echo [OK] Frontend server stopped.
echo ========================================================
echo.

pause
endlocal
