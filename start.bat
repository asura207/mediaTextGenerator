@echo off
chcp 65001 >nul
title TransM - AI Subtitle Studio Launcher

echo ================================================================================
echo                    TransM - AI Subtitle Studio Launcher
echo ================================================================================
echo.

cd /d "%~dp0"

:: 0. Clean up any previous lingering instances on ports 8000 and 5173
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /f /t /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5173" ^| findstr "LISTENING"') do (
    taskkill /f /t /pid %%a >nul 2>&1
)

:: 1. Check Virtual Environment or Python installation
if not exist "%~dp0backend\venv\Scripts\python.exe" (
    where python >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Python이 설치되어 있지 않거나 환경 변수 PATH에 등록되지 않았습니다!
        echo Python 3.10 이상을 설치하신 후 다시 실행해 주세요. (https://www.python.org)
        pause
        exit /b 1
    )
    echo [*] 최초 실행 감지: Python 가상환경(venv)을 생성합니다...
    python -m venv "%~dp0backend\venv"
    if %errorlevel% neq 0 (
        echo [ERROR] 가상환경 생성에 실패했습니다.
        pause
        exit /b 1
    )
    echo [*] 필수 라이브러리를 설치합니다. (최초 1회, 수 분 소요될 수 있습니다)...
    "%~dp0backend\venv\Scripts\python.exe" -m pip install --upgrade pip
    "%~dp0backend\venv\Scripts\python.exe" -m pip install -r "%~dp0backend\requirements.txt"
)

:: 2. Check .env (Run setup_wizard if missing)
if not exist "%~dp0.env" (
    echo [*] 환경설정 파일(.env)이 없습니다. 초기 간편 설정 마법사를 시작합니다...
    echo.
    "%~dp0backend\venv\Scripts\python.exe" "%~dp0setup_wizard.py"
    if not exist "%~dp0.env" (
        echo [ERROR] 설정이 완료되지 않았습니다.
        pause
        exit /b 1
    )
)

:: 3. Check Node.js path in dev tools if exists
if exist "d:\dev\tools\nodejs" (
    set "PATH=d:\dev\tools\nodejs;%PATH%"
)

:: 4. Launch Backend Server
echo [*] Starting Backend Server (FastAPI on Port 8000)...
start "TransM - Backend API" cmd /k "cd /d "%~dp0backend" && "%~dp0backend\venv\Scripts\python.exe" run.py"

:: 5. Check and Launch Frontend
set "DEV_FRONTEND=0"
where npm >nul 2>&1
if %errorlevel% equ 0 (
    if not exist "%~dp0frontend\node_modules" (
        echo [*] Frontend 의존성(npm)을 설치합니다...
        cd /d "%~dp0frontend"
        call npm install
        cd /d "%~dp0"
    )
    echo [*] Starting Frontend Server (Vite on Port 5173)...
    start "TransM - Frontend Studio" cmd /k "cd /d "%~dp0frontend" && npm run dev"
    set "DEV_FRONTEND=1"
) else (
    echo [INFO] Node.js가 감지되지 않아 백엔드 통합 웹 UI(Port 8000)로 구동합니다.
)

echo.
echo ================================================================================
echo [OK] TransM 시스템이 정상 구동되었습니다!
if "%DEV_FRONTEND%"=="1" (
    echo - Web Studio (Vite):    http://localhost:5173
)
echo - Web Studio (통합):   http://localhost:8000
echo - Backend API Docs:    http://localhost:8000/docs
echo ================================================================================
echo.

ping 127.0.0.1 -n 6 >nul
if "%DEV_FRONTEND%"=="1" (
    start http://localhost:5173
) else (
    start http://localhost:8000
)
