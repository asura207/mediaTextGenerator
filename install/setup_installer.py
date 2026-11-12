#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TransM - AI Subtitle Studio One-Click Interactive Installer
비개발자를 위한 단계별(Step-by-Step) 대화형 환경설정 및 설치 마법사
- 1단계: DB 선택 (DB 서버 없음 -> SQLite / DB 서버 있음 -> PostgreSQL 연결 테스트 및 테이블 생성)
- 2단계: LLM 선택 (로컬 LLM PC 사양 기반 모델 자동 추천 / 클라우드 LLM 모델 선택 및 API 키 검증)
- 3단계: Whisper STT 음성인식 사양 맞춤 설정
- 4단계: 미디어 탐색 경로 설정
- 5단계: 환경설정(.env & settings.json) 저장 및 테이블 자동 생성
"""

import sys
import os
import shutil
import subprocess
import platform
import ctypes
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from urllib.parse import quote_plus

# Ensure UTF-8 on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

INSTALL_DIR = Path(__file__).resolve().parent
ROOT_DIR = INSTALL_DIR.parent
BACKEND_DIR = ROOT_DIR / "backend"
ENV_FILE = ROOT_DIR / ".env"
SETTINGS_FILE = BACKEND_DIR / "data" / "settings.json"

# Add backend directory to sys.path so app modules can be loaded
sys.path.insert(0, str(BACKEND_DIR))


def clear_screen():
    os.system("cls" if sys.platform == "win32" else "clear")


def print_banner():
    banner = r"""
================================================================================
  _______                   __  __ 
 |__   __|                 |  \/  |
    | |_ __ __ _ _ __  ___ | \  / |   AI Subtitle Studio One-Click Installer
    | | '__/ _` | '_ \/ __|| |\/| |   (비개발자 원클릭 대화형 설치 마법사)
    | | | | (_| | | | \__ \| |  | |   TransM 자동 배포 & 패키지 설정기
    |_|_|  \__,_|_| |_|___/|_|  |_|
================================================================================
"""
    print(banner)
    print("  반갑습니다! 비개발자도 손쉽게 사용할 수 있도록 최적의 설정을 안내해 드립니다.")
    print("  질문에 번호를 입력하시거나, [Enter] 키를 누르면 권장 기본값으로 설정됩니다.\n")


# ------------------------------------------------------------------------------
# 하드웨어 자동 감지 모듈
# ------------------------------------------------------------------------------
def detect_hardware() -> Dict[str, Any]:
    """PC 사양(CPU, RAM, GPU, CUDA, Ollama, Node.js)을 자동 감지합니다."""
    info: Dict[str, Any] = {
        "python_ver": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "cpu_name": platform.processor() or "Unknown CPU",
        "ram_gb": 8.0,
        "gpu_name": None,
        "gpu_vram_gb": 0.0,
        "has_cuda": False,
        "ollama_installed": False,
        "ollama_running": False,
        "ollama_version": "",
        "node_installed": False,
        "npm_installed": False,
    }

    # 1. RAM 감지 (Windows)
    if sys.platform == "win32":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            info["ram_gb"] = round(stat.ullTotalPhys / (1024 ** 3), 1)
        except Exception:
            pass

    # 2. NVIDIA GPU 감지
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                text=True,
                stderr=subprocess.DEVNULL
            ).strip()
            lines = out.splitlines()
            if lines:
                parts = lines[0].split(",")
                info["gpu_name"] = parts[0].strip()
                info["gpu_vram_gb"] = round(float(parts[1].strip()) / 1024, 1)
                info["has_cuda"] = True
        except Exception:
            pass

    # 3. Ollama 감지
    ollama_path = shutil.which("ollama")
    if ollama_path:
        info["ollama_installed"] = True
        try:
            res = subprocess.run(["ollama", "--version"], capture_output=True, text=True, check=False)
            info["ollama_version"] = (res.stdout.strip() or res.stderr.strip())
        except Exception:
            info["ollama_version"] = "설치됨"

    # Ollama 서비스 활성 상태 확인 (11434 포트)
    try:
        import urllib.request
        req = urllib.request.urlopen("http://localhost:11434/api/version", timeout=1.5)
        if req.status == 200:
            info["ollama_running"] = True
    except Exception:
        info["ollama_running"] = False

    # 4. Node.js & npm 감지
    if shutil.which("node"):
        info["node_installed"] = True
    if shutil.which("npm"):
        info["npm_installed"] = True

    return info


def print_hardware_summary(hw: Dict[str, Any]):
    print("=" * 80)
    print("🖥️  [내 컴퓨터(PC) 사양 자동 분석 결과]")
    print("=" * 80)
    print(f"  • 파이썬 환경   : Python {hw['python_ver']}")
    print(f"  • 시스템 메모리 : {hw['ram_gb']} GB RAM")
    if hw["has_cuda"] and hw["gpu_name"]:
        print(f"  • 그래픽카드    : {hw['gpu_name']} (전용 VRAM {hw['gpu_vram_gb']} GB, NVIDIA CUDA 가속 지원)")
    else:
        print("  • 그래픽카드    : 외장 NVIDIA 그래픽카드 없음 (CPU 고속 연산 모드로 구동)")

    if hw["ollama_running"]:
        print(f"  • Ollama 로컬AI : 현재 백그라운드 실행 중 ({hw['ollama_version']})")
    elif hw["ollama_installed"]:
        print(f"  • Ollama 로컬AI : 설치되어 있음 (실행 대기 상태, {hw['ollama_version']})")
    else:
        print("  • Ollama 로컬AI : 미설치 (로컬 LLM 이용 시 https://ollama.com 에서 간편 설치 가능)")

    if hw["node_installed"] and hw["npm_installed"]:
        print("  • 웹 프론트엔드 : Node.js & npm 설치 확인 완료 (Vite 웹 스튜디오 구동 가능)")
    else:
        print("  • 웹 프론트엔드 : Node.js 미설치 (백엔드 자체 통합 웹 UI로 자동 구동)")
    print("=" * 80 + "\n")


# ------------------------------------------------------------------------------
# 1단계: 데이터베이스(DB) 선택 및 테스트
# ------------------------------------------------------------------------------
def step_database_selection() -> Dict[str, Any]:
    print("=" * 80)
    print("📌 [1단계] 데이터베이스(DB) 선택 및 연동")
    print("=" * 80)
    print("  자막 작업 내역 및 번역 기록을 저장할 데이터베이스 방식을 선택해 주세요:")
    print()
    print("  [1] DB 서버 없음 (★ 강력 추천 / SQLite 파일 DB)")
    print("      • 별도의 DB 서버나 복잡한 프로그램 설치가 전혀 필요 없습니다.")
    print("      • 모든 데이터가 'backend/data/transm.db' 파일에 안전하게 자동 저장됩니다.")
    print("      • 개인 사용자, 일반 PC, 노트북 환경에 가장 안정적이고 빠릅니다.")
    print()
    print("  [2] DB 서버 있음 (외부 PostgreSQL DB 서버 연동)")
    print("      • 사내 또는 별도로 구축된 PostgreSQL 데이터베이스 서버가 있는 경우")
    print("      • 접속 정보(호스트, 포트, 계정, 암호)를 입력받아 실시간 연결 테스트 후")
    print("      • 데이터베이스 및 테이블을 자동으로 생성합니다.")
    print("-" * 80)

    while True:
        choice = input("선택하세요 [기본값: 1 (DB 서버 없음)]: ").strip() or "1"
        if choice in ("1", "sqlite", "없음"):
            print("\n>> [선택 완료] 'DB 서버 없음 (SQLite)' 방식을 사용합니다.")
            db_dir = BACKEND_DIR / "data"
            db_dir.mkdir(parents=True, exist_ok=True)
            return {
                "DB_TYPE": "sqlite",
                "SQLITE_PATH": "backend/data/transm.db",
                "POSTGRES_HOST": "localhost",
                "POSTGRES_PORT": "5432",
                "POSTGRES_DB": "transm",
                "POSTGRES_USER": "postgres",
                "POSTGRES_PASSWORD": "",
            }
        elif choice in ("2", "postgres", "postgresql", "있음"):
            print("\n>> [선택 완료] PostgreSQL DB 서버 접속 정보를 입력해 주세요:")
            host = input("  • DB 호스트 주소 [기본값: localhost]: ").strip() or "localhost"
            port_str = input("  • DB 포트 번호 [기본값: 5432]: ").strip() or "5432"
            dbname = input("  • 데이터베이스 이름 [기본값: transm]: ").strip() or "transm"
            user = input("  • 사용자 계정명 [기본값: postgres]: ").strip() or "postgres"
            password = input("  • 계정 비밀번호 (Enter 시 빈값): ").strip()

            print(f"\n[*] PostgreSQL 서버({host}:{port_str}) 연결 테스트 중...")
            success, err_msg = test_and_prepare_postgres(host, int(port_str), user, password, dbname)

            if success:
                print(f"[OK] PostgreSQL 서버 연결 성공! '{dbname}' 데이터베이스가 확인되었습니다.\n")
                return {
                    "DB_TYPE": "postgres",
                    "SQLITE_PATH": "backend/data/transm.db",
                    "POSTGRES_HOST": host,
                    "POSTGRES_PORT": port_str,
                    "POSTGRES_DB": dbname,
                    "POSTGRES_USER": user,
                    "POSTGRES_PASSWORD": password,
                }
            else:
                print(f"\n⚠️  [연결 실패] PostgreSQL 접속 중 오류가 발생했습니다:")
                print(f"    -> {err_msg}")
                print("\n  어떻게 진행하시겠습니까?")
                print("  [1] 접속 정보 다시 입력 (재시도)")
                print("  [2] DB 서버 없음(SQLite 파일 DB)으로 안전하게 전환 (추천)")
                print("  [3] 실패 무시하고 입력한 설정값 그대로 저장")
                sub_choice = input("선택하세요 [기본값: 2 (SQLite 전환)]: ").strip() or "2"
                if sub_choice == "1":
                    continue
                elif sub_choice == "3":
                    return {
                        "DB_TYPE": "postgres",
                        "SQLITE_PATH": "backend/data/transm.db",
                        "POSTGRES_HOST": host,
                        "POSTGRES_PORT": port_str,
                        "POSTGRES_DB": dbname,
                        "POSTGRES_USER": user,
                        "POSTGRES_PASSWORD": password,
                    }
                else:
                    print("\n>> 안전을 위해 SQLite 파일 DB 모드로 자동 전환합니다.\n")
                    return {
                        "DB_TYPE": "sqlite",
                        "SQLITE_PATH": "backend/data/transm.db",
                        "POSTGRES_HOST": "localhost",
                        "POSTGRES_PORT": "5432",
                        "POSTGRES_DB": "transm",
                        "POSTGRES_USER": "postgres",
                        "POSTGRES_PASSWORD": "",
                    }
        else:
            print("올바른 번호(1 또는 2)를 입력해 주세요.")


def test_and_prepare_postgres(host: str, port: int, user: str, password: str, dbname: str) -> Tuple[bool, str]:
    """Tests connection to PostgreSQL and auto-creates the database if not existing."""
    try:
        from sqlalchemy import create_engine, text
        encoded_pw = quote_plus(password)

        # 1. 대상 DB 직접 연결 시도
        target_url = f"postgresql+psycopg2://{user}:{encoded_pw}@{host}:{port}/{dbname}"
        try:
            eng = create_engine(target_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            eng.dispose()
            return True, ""
        except Exception as e_target:
            target_err = str(e_target)

        # 2. 만약 DB가 없다면 관리자 DB(postgres, template1)를 통해 CREATE DATABASE 시도
        admin_dbs = ["postgres", "template1"]
        admin_connected = False
        for admin_db in admin_dbs:
            admin_url = f"postgresql+psycopg2://{user}:{encoded_pw}@{host}:{port}/{admin_db}"
            try:
                admin_eng = create_engine(admin_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
                with admin_eng.connect() as conn:
                    exists = conn.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                        {"dbname": dbname}
                    ).scalar()
                    if not exists:
                        print(f"[*] '{dbname}' 데이터베이스가 존재하지 않아 신규 생성합니다...")
                        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
                        print(f"[OK] 데이터베이스 '{dbname}' 생성 완료!")
                admin_eng.dispose()
                admin_connected = True
                return True, ""
            except Exception:
                continue

        return False, target_err
    except Exception as e:
        return False, str(e)


# ------------------------------------------------------------------------------
# 2단계: AI 번역 및 문맥 교정 LLM 엔진 선택
# ------------------------------------------------------------------------------
def step_llm_selection(hw: Dict[str, Any]) -> Dict[str, Any]:
    print("=" * 80)
    print("📌 [2단계] AI 번역 및 문맥 교정 LLM 엔진 선택")
    print("=" * 80)
    print("  자막의 어색한 직역을 다듬고 20년 차 번역가 수준의 유려한 구어체로 교정할")
    print("  인공지능(LLM) 방식을 선택해 주세요:")
    print()
    print("  [1] 로컬 LLM (★ 무료 / 내 PC 하드웨어에서 오프라인으로 구동 - Ollama)")
    print("      • 사용료 0원, 인터넷 연결 없이도 안전하게 내 컴퓨터에서 처리")
    print("      • 현재 PC 사양(RAM, 그래픽카드 VRAM)을 분석하여 최적의 모델을 자동 추천합니다.")
    print()
    print("  [2] 클라우드 LLM (★ 최고 품질 & 저사양 PC 초고속 / OpenAI, Claude, Gemini)")
    print("      • PC 사양이 낮아도 초고속으로 대용량 자막 번역 및 고품질 한국어 교정 가능")
    print("      • OpenAI(GPT-4o), Anthropic(Claude 3.5), Google(Gemini 2.5) API 키 입력")
    print("-" * 80)

    choice = input("선택하세요 [기본값: 1 (로컬 LLM)]: ").strip() or "1"

    if choice in ("1", "local", "로컬", "ollama"):
        return configure_local_llm(hw)
    else:
        return configure_cloud_llm()


def configure_local_llm(hw: Dict[str, Any]) -> Dict[str, Any]:
    """Analyzes hardware specs and guides local Ollama model selection."""
    vram = hw.get("gpu_vram_gb", 0.0)
    ram = hw.get("ram_gb", 8.0)
    has_cuda = hw.get("has_cuda", False)

    # 사양별 모델 추천 로직
    if has_cuda and vram >= 10.0 and ram >= 24.0:
        recommended_model = "qwen2.5:14b"
        rec_reason = f"RTX 4070 Ti급 고사양 GPU(VRAM {vram}GB)와 {ram}GB RAM이 감지되어, 자막 번역 품질이 가장 뛰어난 14B 고성능 모델을 추천합니다."
    elif has_cuda and vram >= 6.0 and ram >= 12.0:
        recommended_model = "qwen2.5:7b"
        rec_reason = f"표준 밸런스 사양(VRAM {vram}GB, RAM {ram}GB)에 최적화되어 빠른 속도와 고품질 번역을 균형 있게 제공하는 7B 모델을 추천합니다."
    else:
        recommended_model = "qwen2.5:3b"
        rec_reason = f"가벼운 저사양 PC/노트북 환경(RAM {ram}GB)에 맞춰 끊김 없이 부드럽게 구동되는 3B 초경량 고효율 모델을 추천합니다."

    print("\n" + "=" * 80)
    print("🤖 [로컬 LLM 모델 추천 및 선택]")
    print("=" * 80)
    print(f"  👉 시스템 분석 추천: [{recommended_model}]")
    print(f"     사유: {rec_reason}")
    print("-" * 80)
    print("  원하시는 모델 번호를 선택하세요:")
    print(f"  [1] (★ 추천) {recommended_model} - 시스템 맞춤 최적 모델")
    print("  [2] qwen2.5:14b   - (권장 고사양) 한/영/중/일 자막 번역 및 구어체 최고 품질")
    print("  [3] qwen2.5:7b    - (표준 밸런스) 빠른 처리 속도와 우수한 번역 품질")
    print("  [4] qwen2.5:3b    - (저사양/노트북) 3B 초경량 고효율 로컬 AI 모델")
    print("  [5] gemma4:12b    - (Google 최신 모델)")
    print("  [6] 직접 모델명 입력 (Custom)")
    print("-" * 80)

    m_choice = input(f"선택하세요 [기본값: 1 ({recommended_model})]: ").strip() or "1"
    model_map = {
        "1": recommended_model,
        "2": "qwen2.5:14b",
        "3": "qwen2.5:7b",
        "4": "qwen2.5:3b",
        "5": "gemma4:12b",
    }

    if m_choice in model_map:
        selected_model = model_map[m_choice]
    elif m_choice == "6":
        selected_model = input("사용하실 Ollama 모델명을 입력하세요 (예: llama3.1:8b): ").strip() or recommended_model
    else:
        selected_model = recommended_model

    batch_size = 10 if "14b" in selected_model else (8 if "7b" in selected_model else 5)
    print(f"\n>> 선택된 로컬 모델: {selected_model} (배치 크기: {batch_size})")

    # Ollama 모델 설치 여부 확인 및 자동 다운로드 제안
    if hw["ollama_installed"]:
        _check_and_pull_ollama(selected_model)
    else:
        print("\n⚠️  [안내] Ollama 프로그램이 아직 설치되어 있지 않습니다.")
        print("   -> https://ollama.com 에서 무료로 다운로드 후 설치하시면 자동으로 연동됩니다.")

    return {
        "LLM_PROVIDER": "ollama",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_MODEL": selected_model,
        "LLM_BATCH_SIZE": batch_size,
        "OPENAI_API_KEY": "",
        "OPENAI_MODEL": "gpt-4o",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_MODEL": "claude-3-5-sonnet-latest",
        "GEMINI_API_KEY": "",
        "GEMINI_MODEL": "gemini-2.5-flash",
    }


def _check_and_pull_ollama(model_name: str):
    """Checks if the chosen model is present in Ollama, offering to download it."""
    is_present = False
    try:
        out = subprocess.check_output(["ollama", "list"], text=True, stderr=subprocess.DEVNULL)
        if model_name.split(":")[0] in out:
            is_present = True
    except Exception:
        pass

    if is_present:
        print(f"[OK] '{model_name}' 모델이 이미 내 PC에 설치되어 있습니다.")
    else:
        pull_ask = input(f"\n지금 Ollama를 통해 '{model_name}' 모델을 다운로드하시겠습니까? (Y/n) [기본값: Y]: ").strip().lower()
        if pull_ask in ("", "y", "yes"):
            print(f"[*] 'ollama pull {model_name}' 다운로드 시작... (네트워크 속도에 따라 수 분 소요)")
            try:
                ret = subprocess.run(["ollama", "pull", model_name], check=False)
                if ret.returncode == 0:
                    print(f"[OK] '{model_name}' 모델 다운로드 및 준비 완료!")
                else:
                    print(f"⚠️ 다운로드 중 오류가 발생했습니다. 추후 터미널에서 'ollama pull {model_name}'을 실행하실 수 있습니다.")
            except Exception as e:
                print(f"⚠️ Ollama 실행 오류: {e}")


def configure_cloud_llm() -> Dict[str, Any]:
    """Configures Cloud LLM provider, model, API key, and tests connectivity."""
    print("\n" + "=" * 80)
    print("☁️  [클라우드 LLM 설정]")
    print("=" * 80)
    print("  사용하실 클라우드 인공지능 서비스를 선택하세요:")
    print("  [1] Google Gemini  (★ 강력 추천 / 초고속 속도, 방대한 컨텍스트, 합리적 비용)")
    print("  [2] OpenAI         (GPT-4o, GPT-4o-mini 등 표준 고품질 모델)")
    print("  [3] Anthropic      (Claude 3.5 Sonnet 등 뛰어난 한국어 뉘앙스 표현)")
    print("-" * 80)

    p_choice = input("선택하세요 [기본값: 1 (Google Gemini)]: ").strip() or "1"
    provider_map = {
        "1": ("gemini", "gemini-2.5-flash", ["gemini-2.5-flash (초고속 추천)", "gemini-2.5-pro (최고 품질)", "gemini-1.5-flash"]),
        "2": ("openai", "gpt-4o", ["gpt-4o (최고 품질 플래그십)", "gpt-4o-mini (가볍고 빠른 가성비)", "o3-mini"]),
        "3": ("anthropic", "claude-3-5-sonnet-latest", ["claude-3-5-sonnet-latest (최고 품질)", "claude-3-5-haiku-latest (초고속 경량)"]),
    }

    prov_key, default_model, model_candidates = provider_map.get(p_choice, provider_map["1"])

    print(f"\n>> 사용할 [{prov_key.upper()}] 세부 모델을 선택하세요:")
    for idx, cand in enumerate(model_candidates, start=1):
        print(f"  [{idx}] {cand}")
    print(f"  [{len(model_candidates) + 1}] 직접 모델명 입력")

    m_idx = input(f"선택하세요 [기본값: 1 ({default_model})]: ").strip() or "1"
    try:
        idx_int = int(m_idx)
        if 1 <= idx_int <= len(model_candidates):
            selected_model = model_candidates[idx_int - 1].split()[0]
        else:
            selected_model = input("모델명을 직접 입력하세요: ").strip() or default_model
    except Exception:
        selected_model = default_model

    print(f"\n>> {prov_key.upper()} API 키를 입력해 주세요:")
    api_key = input("  • API Key: ").strip()

    # API 키 실시간 연결 테스트
    if api_key:
        print(f"\n[*] {prov_key.upper()} '{selected_model}' 연결 테스트 진행 중...")
        test_res = test_cloud_api(prov_key, api_key, selected_model)
        if test_res.get("success"):
            print(f"[OK] {prov_key.upper()} API 연결 테스트 성공! (응답 시간: {test_res.get('latency_ms', 0)}ms)")
        else:
            print(f"⚠️  [연결 확인 알림] {test_res.get('message', '연결 실패')}")
            print("   -> 키가 올바른지 확인해 주세요. (설정값은 그대로 저장되며 추후 관리자 설정에서 수정 가능)")

    return {
        "LLM_PROVIDER": prov_key,
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_MODEL": "qwen2.5:14b",
        "LLM_BATCH_SIZE": 10,
        "OPENAI_API_KEY": api_key if prov_key == "openai" else "",
        "OPENAI_MODEL": selected_model if prov_key == "openai" else "gpt-4o",
        "ANTHROPIC_API_KEY": api_key if prov_key == "anthropic" else "",
        "ANTHROPIC_MODEL": selected_model if prov_key == "anthropic" else "claude-3-5-sonnet-latest",
        "GEMINI_API_KEY": api_key if prov_key == "gemini" else "",
        "GEMINI_MODEL": selected_model if prov_key == "gemini" else "gemini-2.5-flash",
    }


def test_cloud_api(provider: str, api_key: str, model: str) -> Dict[str, Any]:
    """Calls app.services.llm_provider.test_provider_connectivity."""
    try:
        from app.services.llm_provider import test_provider_connectivity
        return test_provider_connectivity(provider=provider, api_key=api_key, model=model)
    except Exception as e:
        return {"success": False, "message": str(e)}


# ------------------------------------------------------------------------------
# 3단계: Whisper 음성 인식(STT) 사양 맞춤 설정
# ------------------------------------------------------------------------------
def step_whisper_selection(hw: Dict[str, Any]) -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print("📌 [3단계] Whisper 음성 인식(STT) 사양 맞춤 설정")
    print("=" * 80)
    has_cuda = hw.get("has_cuda", False)
    vram = hw.get("gpu_vram_gb", 0.0)

    if has_cuda and vram >= 6.0:
        recommended_whisper = "large-v3-turbo"
        device = "cuda"
        compute_type = "float16"
        reason = f"NVIDIA GPU({hw.get('gpu_name')}, VRAM {vram}GB) 가속을 활용해 최고 속도와 정확도를 자랑하는 large-v3-turbo 모델을 적용합니다."
    elif has_cuda:
        recommended_whisper = "medium"
        device = "cuda"
        compute_type = "float16"
        reason = f"GPU VRAM({vram}GB)에 최적화된 밸런스형 medium 모델을 적용합니다."
    else:
        recommended_whisper = "small"
        device = "cpu"
        compute_type = "int8"
        reason = "외장 GPU가 없으므로 저사양 PC/노트북 CPU에서 가볍고 빠르게 동작하는 small(int8) 경량 모델을 적용합니다."

    print(f"  👉 Whisper 권장 설정: [{recommended_whisper}] ({device.upper()} / {compute_type})")
    print(f"     사유: {reason}")
    print("-" * 80)
    print("  [1] (★ 권장) large-v3-turbo (음성 인식 속도와 정확도 모두 최상)")
    print("  [2] large-v3       (최고 수준의 정확도, 다소 무거움)")
    print("  [3] medium         (중간 사양 밸런스형)")
    print("  [4] small          (🍃 저사양 PC / 노트북 CPU 전용 경량 모델)")
    print("  [5] base           (초경량 테스트용)")
    print("-" * 80)

    w_choice = input("선택하세요 [기본값: 1 (large-v3-turbo)]: ").strip() or "1"
    w_map = {
        "1": "large-v3-turbo",
        "2": "large-v3",
        "3": "medium",
        "4": "small",
        "5": "base",
    }
    model_size = w_map.get(w_choice, recommended_whisper)

    return {
        "WHISPER_MODEL_SIZE": model_size,
        "WHISPER_DEVICE": device,
        "WHISPER_COMPUTE_TYPE": compute_type,
    }


# ------------------------------------------------------------------------------
# 4단계: 미디어 탐색 경로 설정
# ------------------------------------------------------------------------------
def step_media_scan_directories() -> str:
    print("\n" + "=" * 80)
    print("📌 [4단계] 동영상 미디어 폴더 탐색 경로 설정")
    print("=" * 80)
    print("  TransM에서 원클릭으로 탐색할 PC 내 영상/미디어 폴더 경로를 입력하세요.")
    print("  (여러 폴더는 쉼표[,]로 구분하여 입력하실 수 있습니다.)")
    print("  예시: D:\\Videos, D:\\Media, C:\\Users\\User\\Videos")
    print("  (Enter 입력 시 기본 추천 경로가 자동으로 등록됩니다.)")
    print("-" * 80)

    default_dirs = "D:\\Videos,D:\\Media"
    user_dirs = input(f"입력 [기본값: {default_dirs}]: ").strip()
    return user_dirs or default_dirs


# ------------------------------------------------------------------------------
# 5단계: 환경설정 파일(.env 및 settings.json) 저장
# ------------------------------------------------------------------------------
def save_configurations(cfg: Dict[str, Any]):
    print("\n" + "=" * 80)
    print("💾 [5단계] 환경설정 파일(.env & settings.json) 생성 및 저장")
    print("=" * 80)

    # 1. .env 파일 생성
    media_scan_dirs_val = cfg.get("MEDIA_SCAN_DIRS", r"D:\Videos,D:\Media")
    env_content = f"""# ==============================================================================
# TransM - AI Subtitle Studio Environment Configuration
# Automatically generated by TransM Setup Installer
# Generated At: {time.strftime('%Y-%m-%d %H:%M:%S')}
# ==============================================================================

# Server Network Config
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# Database Configuration ('sqlite' or 'postgres')
DB_TYPE={cfg.get("DB_TYPE", "sqlite")}
SQLITE_PATH={cfg.get("SQLITE_PATH", "backend/data/transm.db")}

# PostgreSQL Database Settings (Used when DB_TYPE=postgres)
POSTGRES_HOST={cfg.get("POSTGRES_HOST", "localhost")}
POSTGRES_PORT={cfg.get("POSTGRES_PORT", "5432")}
POSTGRES_DB={cfg.get("POSTGRES_DB", "transm")}
POSTGRES_USER={cfg.get("POSTGRES_USER", "postgres")}
POSTGRES_PASSWORD={cfg.get("POSTGRES_PASSWORD", "")}

# Active LLM Provider ('ollama', 'openai', 'anthropic', 'gemini')
LLM_PROVIDER={cfg.get("LLM_PROVIDER", "ollama")}

# Local LLM Service (Ollama)
OLLAMA_HOST={cfg.get("OLLAMA_HOST", "http://localhost:11434")}
OLLAMA_MODEL={cfg.get("OLLAMA_MODEL", "qwen2.5:14b")}
LLM_BATCH_SIZE={cfg.get("LLM_BATCH_SIZE", 10)}

# Cloud LLM API Credentials & Models
OPENAI_API_KEY={cfg.get("OPENAI_API_KEY", "")}
OPENAI_MODEL={cfg.get("OPENAI_MODEL", "gpt-4o")}
ANTHROPIC_API_KEY={cfg.get("ANTHROPIC_API_KEY", "")}
ANTHROPIC_MODEL={cfg.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")}
GEMINI_API_KEY={cfg.get("GEMINI_API_KEY", "")}
GEMINI_MODEL={cfg.get("GEMINI_MODEL", "gemini-2.5-flash")}

# Whisper Speech-to-Text Engine
WHISPER_MODEL_SIZE={cfg.get("WHISPER_MODEL_SIZE", "large-v3-turbo")}
WHISPER_DEVICE={cfg.get("WHISPER_DEVICE", "cuda")}
WHISPER_COMPUTE_TYPE={cfg.get("WHISPER_COMPUTE_TYPE", "float16")}

# Media Scan Root Directories (Server-side search)
MEDIA_SCAN_DIRS={media_scan_dirs_val}
"""
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write(env_content)
    print(f"  [OK] 프로젝트 환경설정 파일 생성 완료: {ENV_FILE.name}")

    # 2. backend/data/settings.json 런타임 캐시 동기화
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    import json
    runtime_dict = {
        "llm_provider": cfg.get("LLM_PROVIDER", "ollama"),
        "ollama_model": cfg.get("OLLAMA_MODEL", "qwen2.5:14b"),
        "llm_batch_size": cfg.get("LLM_BATCH_SIZE", 10),
        "whisper_model_size": cfg.get("WHISPER_MODEL_SIZE", "large-v3-turbo"),
        "whisper_device": cfg.get("WHISPER_DEVICE", "cuda"),
        "whisper_compute_type": cfg.get("WHISPER_COMPUTE_TYPE", "float16"),
        "openai_api_key": cfg.get("OPENAI_API_KEY", ""),
        "openai_model": cfg.get("OPENAI_MODEL", "gpt-4o"),
        "anthropic_api_key": cfg.get("ANTHROPIC_API_KEY", ""),
        "anthropic_model": cfg.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
        "gemini_api_key": cfg.get("GEMINI_API_KEY", ""),
        "gemini_model": cfg.get("GEMINI_MODEL", "gemini-2.5-flash"),
    }
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(runtime_dict, f, ensure_ascii=False, indent=2)
    print(f"  [OK] 런타임 설정 동기화 완료: {SETTINGS_FILE.name}")


# ------------------------------------------------------------------------------
# 6단계: 데이터베이스 테이블 초기화 실행
# ------------------------------------------------------------------------------
def step_initialize_database_tables():
    print("\n" + "=" * 80)
    print("🛠️  [6단계] 데이터베이스 테이블 생성 및 스키마 초기화")
    print("=" * 80)
    try:
        from install.init_database import run_init_database
        success = run_init_database()
        if success:
            print("[OK] 데이터베이스 모든 테이블(작업내역, 완료보관함, 대기열, 고유명사사전) 준비 완료!")
        else:
            print("⚠️ 테이블 초기화 중 일부 경고가 발생했습니다.")
    except Exception as e:
        print(f"⚠️ 테이블 초기화 모듈 호출 오류: {e}")


def main():
    print_banner()

    # Step 0: 하드웨어 사양 감지
    hw_info = detect_hardware()
    print_hardware_summary(hw_info)

    # Step 1: 데이터베이스 선택
    db_cfg = step_database_selection()

    # Step 2: LLM 선택 (로컬 vs 클라우드)
    llm_cfg = step_llm_selection(hw_info)

    # Step 3: Whisper STT 설정
    whisper_cfg = step_whisper_selection(hw_info)

    # Step 4: 미디어 탐색 경로 설정
    media_dirs = step_media_scan_directories()

    # 통합 설정 딕셔너리 생성
    final_config = {
        **db_cfg,
        **llm_cfg,
        **whisper_cfg,
        "MEDIA_SCAN_DIRS": media_dirs,
    }

    # Step 5: 설정 파일 저장
    save_configurations(final_config)

    # Step 6: 데이터베이스 테이블 초기화
    step_initialize_database_tables()

    print("\n" + "=" * 80)
    print("🎉 축하합니다! TransM 원클릭 환경 설정 및 설치가 완벽히 완료되었습니다!")
    print("=" * 80)
    print("  [바로 실행하는 방법]")
    print("  1. 'start.bat' 또는 'install/start_transm.bat'을 더블클릭하시면")
    print("     서버와 웹 브라우저가 원클릭으로 자동 실행됩니다.")
    print("  2. 웹 브라우저 주소: http://localhost:5173 (또는 http://localhost:8000)")
    print("  3. 설정을 변경하고 싶을 때는 언제든지 'install/install.bat'을 다시 실행하세요.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
