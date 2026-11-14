@echo off
chcp 65001 >nul
title TransM - AI Subtitle Studio Launcher

echo ================================================================================
echo                    TransM - AI Subtitle Studio Launcher
echo ================================================================================
echo.

rem 프로젝트 루트 디렉터리로 이동
cd /d "%~dp0.."

rem 0. 기존 잔여 프로세스 정리 [8000, 5173 포트]
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /f /t /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5173" ^| findstr "LISTENING"') do (
    taskkill /f /t /pid %%a >nul 2>&1
)

rem 1. Python 가상환경 확인
if not exist "%~dp0..\backend\venv\Scripts\python.exe" (
    where python >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Python이 설치되어 있지 않거나 환경 변수 PATH에 등록되지 않았습니다!
        echo Python 3.10 이상을 설치하신 후 다시 실행해 주세요. - https://www.python.org
        pause
        exit /b 1
    )
    echo [*] Python 가상환경이 감지되지 않아 설치 마법사를 먼저 실행합니다...
    call "%~dp0install.bat"
    exit /b 0
)

rem 2. 환경 설정 파일[.env] 확인
if not exist "%~dp0..\.env" (
    echo [*] 환경설정 파일 [.env] 이 없습니다. 설치 마법사를 실행합니다...
    "%~dp0..\backend\venv\Scripts\python.exe" "%~dp0setup_installer.py"
    if not exist "%~dp0..\.env" (
        echo [ERROR] 설정이 완료되지 않았습니다.
        pause
        exit /b 1
    )
)

rem 3. 백엔드 서버 실행 [FastAPI :8000]
echo [*] 백엔드 서버 시작 중 [FastAPI on Port 8000]...
start "TransM - Backend API" /D "%~dp0..\backend" cmd /k "call start_backend.bat"

rem 4. 프론트엔드 서버 실행 [Vite :5173]
set "DEV_FRONTEND=0"
where npm >nul 2>&1
if %errorlevel% equ 0 (
    if not exist "%~dp0..\frontend\node_modules" (
        echo [*] Frontend 의존성 [npm install] 을 진행합니다...
        pushd "%~dp0..\frontend"
        call npm install
        popd
    )
    echo [*] 프론트엔드 웹 스튜디오 시작 중 [Vite on Port 5173]...
    start "TransM - Frontend Studio" /D "%~dp0..\frontend" cmd /k "call start_frontend.bat"
    set "DEV_FRONTEND=1"
) else (
    echo [INFO] Node.js가 감지되지 않아 백엔드 통합 웹 UI [Port 8000] 로 구동합니다.
)

echo.
echo ================================================================================
echo [OK] TransM 시스템이 정상 구동되었습니다!
if "%DEV_FRONTEND%"=="1" (
    echo - Web Studio [Vite]:    http://localhost:5173
)
echo - Web Studio [통합]:    http://localhost:8000
echo - Backend API Docs:     http://localhost:8000/docs
echo ================================================================================
echo.
echo [*] 웹 브라우저를 띄우기 위해 잠시 대기합니다...

ping 127.0.0.1 -n 6 >nul
if "%DEV_FRONTEND%"=="1" (
    start "" "http://localhost:5173"
) else (
    start "" "http://localhost:8000"
)

echo.
echo [안내] 백엔드 및 프론트엔드 창이 별도의 콘솔 창으로 정상 실행 중입니다.
echo 창을 닫으시면 해당 서비스가 종료됩니다.

