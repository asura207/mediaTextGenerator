@echo off
setlocal
title TransM - Stop Backend (:8000)

echo ========================================================
echo         TransM - Stop Backend (FastAPI :8000)
echo ========================================================
echo.

echo [*] Checking Backend on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo [*] Terminating Backend process PID %%a
    taskkill /f /t /pid %%a >nul 2>&1
)

echo.
echo ========================================================
echo [OK] Backend server stopped.
echo ========================================================
echo.

pause
endlocal
