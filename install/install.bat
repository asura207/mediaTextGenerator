@echo off
chcp 65001 >nul
title TransM - AI Subtitle Studio One-Click Installer

echo ================================================================================
echo          TransM - AI Subtitle Studio 원클릭 통합 설치 및 설정 마법사
echo ================================================================================
echo.
echo  비개발자를 위한 원클릭 패키지 설치를 시작합니다.
echo  필요한 프로그램 환경 점검부터 의존성 설치, 데이터베이스 연결, AI 모델 설정까지
echo  한 번에 자동으로 진행됩니다.
echo.
echo ================================================================================

cd /d "%~dp0.."

rem 1. Python 설치 확인
set "PYTHON_EXE="
if exist "%~dp0..\backend\venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0..\backend\venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] 시스템에 Python이 설치되어 있지 않거나 환경 변수(PATH)에 등록되지 않았습니다!
        echo.
        echo 1. https://www.python.org/downloads/ 에서 Python 3.10 이상을 다운로드하세요.
        echo 2. 설치 시 반드시 하단의 [Add Python to PATH] 체크박스를 선택해 주세요!
        echo.
        set /p OPEN_PY="지금 Python 공식 다운로드 웹페이지를 여시겠습니까? (Y/n): "
        if /i "%OPEN_PY%"=="y" start https://www.python.org/downloads/
        if "%OPEN_PY%"=="" start https://www.python.org/downloads/
        pause
        exit /b 1
    )
    set "PYTHON_EXE=python"
)

rem 2. Python 가상환경(venv) 생성 및 필수 라이브러리 설치
if not exist "%~dp0..\backend\venv\Scripts\python.exe" (
    echo.
    echo [*] [1/4] Python 독립 가상환경(backend\venv)을 생성합니다...
    python -m venv "%~dp0..\backend\venv"
    if %errorlevel% neq 0 (
        echo [ERROR] 가상환경 생성에 실패했습니다. 관리자 권한으로 다시 실행해 주세요.
        pause
        exit /b 1
    )
    set "PYTHON_EXE=%~dp0..\backend\venv\Scripts\python.exe"
    echo [OK] 가상환경이 성공적으로 생성되었습니다.
    echo.
    echo [*] [2/4] AI 자막 파이프라인 필수 패키지를 설치합니다 (최초 1회, 수 분 소요)...
    "%PYTHON_EXE%" -m pip install --upgrade pip
    "%PYTHON_EXE%" -m pip install -r "%~dp0..\backend\requirements.txt"
    if %errorlevel% neq 0 (
        echo [WARNING] 일부 패키지 설치 중 경고가 발생했으나 설치를 계속 진행합니다.
    )
) else (
    set "PYTHON_EXE=%~dp0..\backend\venv\Scripts\python.exe"
    echo [OK] Python 가상환경이 이미 준비되어 있습니다.
)

rem 3. 대화형 설정 마법사 실행 (DB 선택, LLM 추천/선택, STT 설정, 테이블 생성)
echo.
echo [*] [3/4] 대화형 설치 및 환경설정 마법사를 시작합니다...
"%PYTHON_EXE%" "%~dp0setup_installer.py"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] 설정 마법사 실행 중 오류가 발생했습니다.
    pause
    exit /b 1
)

rem 4. 프론트엔드 웹 스튜디오 빌드 (Node.js 감지 시)
echo.
echo [*] [4/4] 웹 프론트엔드 환경을 점검합니다...
where npm >nul 2>&1
if %errorlevel% equ 0 (
    if not exist "%~dp0..\frontend\node_modules" (
        echo [*] Frontend 의존성 패키지를 설치합니다 (npm install)...
        cd /d "%~dp0..\frontend"
        call npm install
        cd /d "%~dp0.."
    )
    if not exist "%~dp0..\frontend\dist" (
        echo [*] 프로덕션 웹 번들을 빌드합니다 (npm run build)...
        cd /d "%~dp0..\frontend"
        call npm run build
        cd /d "%~dp0.."
    )
    echo [OK] 프론트엔드 준비가 완료되었습니다.
) else (
    echo [INFO] Node.js가 감지되지 않았으나, 백엔드 내장 UI 모드로 정상 사용하실 수 있습니다.
)

rem 5. 바탕화면 바로가기 아이콘 생성
echo.
set /p CREATE_ICON="바탕화면에 'TransM AI 자막 스튜디오' 바로가기 아이콘을 생성하시겠습니까? (Y/n) [기본값: Y]: "
if /i "%CREATE_ICON%"=="y" goto MAKE_SHORTCUT
if "%CREATE_ICON%"=="" goto MAKE_SHORTCUT
goto AFTER_SHORTCUT

:MAKE_SHORTCUT
cscript //nologo "%~dp0create_desktop_shortcut.vbs"
:AFTER_SHORTCUT

echo.
echo ================================================================================
echo 🎉 TransM 설치가 성공적으로 완료되었습니다!
echo ================================================================================
echo.
set /p LAUNCH_NOW="지금 TransM 프로그램을 바로 실행하시겠습니까? (Y/n) [기본값: Y]: "
if /i "%LAUNCH_NOW%"=="y" goto LAUNCH_APP
if "%LAUNCH_NOW%"=="" goto LAUNCH_APP
echo.
echo [안내] 언제든지 'install\start_transm.bat' 또는 바탕화면 아이콘으로 실행하실 수 있습니다.
pause
exit /b 0

:LAUNCH_APP
echo.
echo [*] TransM 시스템을 가동합니다...
call "%~dp0start_transm.bat"
exit /b 0
