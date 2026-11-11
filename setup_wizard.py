#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TransM - AI Subtitle Studio Setup Wizard (대화형 간편 설치 및 환경설정 마법사)
비개발자도 쉽게 PC 사양별 프리셋(권장 고사양 / 표준 밸런스 / 저사양 노트북)을 선택하여
DB(SQLite/PostgreSQL)와 로컬 LLM 모델을 원클릭으로 설정하고 즉시 구동할 수 있습니다.
"""

import sys
import os
import shutil
import subprocess
import platform
import ctypes
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from urllib.parse import quote_plus

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent
ENV_FILE = ROOT_DIR / ".env"
ENV_EXAMPLE = ROOT_DIR / ".env.example"


def print_banner():
    banner = r"""
================================================================================
  _______                   __  __ 
 |__   __|                 |  \/  |
    | |_ __ __ _ _ __  ___ | \  / |
    | | '__/ _` | '_ \/ __|| |\/| |   AI Subtitle Studio Setup Wizard
    | | | | (_| | | | \__ \| |  | |   (대화형 간편 설치 & 환경설정 마법사)
    |_|_|  \__,_|_| |_|___/|_|  |_|
================================================================================
    """
    print(banner)
    print("  TransM 환경 설정을 시작합니다. 시스템 사양에 맞춘 최적 프리셋을 제공합니다.\n")


def detect_system_hardware() -> Dict[str, Any]:
    """Detects CPU, RAM, and NVIDIA GPU specs to recommend the best preset."""
    info: Dict[str, Any] = {
        "python_ver": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "cpu_name": platform.processor() or "Unknown CPU",
        "ram_gb": 8.0,
        "gpu_name": None,
        "gpu_vram_gb": 0.0,
        "has_cuda": False,
        "ollama_installed": False,
        "ollama_version": "",
        "recommended_preset": "1",
    }

    # 1. Detect RAM on Windows
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

    # 2. Detect NVIDIA GPU
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

    # Fallback to torch cuda check if available
    if not info["has_cuda"]:
        try:
            import torch
            if torch.cuda.is_available():
                info["has_cuda"] = True
                info["gpu_name"] = torch.cuda.get_device_name(0)
                info["gpu_vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 1)
        except Exception:
            pass

    # 3. Detect Ollama
    ollama_path = shutil.which("ollama")
    if ollama_path:
        info["ollama_installed"] = True
        try:
            res = subprocess.run(["ollama", "--version"], capture_output=True, text=True, check=False)
            info["ollama_version"] = (res.stdout.strip() or res.stderr.strip())
        except Exception:
            info["ollama_version"] = "설치됨"

    # 4. Determine recommendation
    if info["has_cuda"] and info["gpu_vram_gb"] >= 10.0 and info["ram_gb"] >= 24.0:
        info["recommended_preset"] = "1"  # 권장 고사양 프리셋 (내 PC 기준: 4070 Ti, 32GB)
    elif info["has_cuda"] and info["gpu_vram_gb"] >= 6.0 and info["ram_gb"] >= 12.0:
        info["recommended_preset"] = "2"  # 밸런스 프리셋
    else:
        info["recommended_preset"] = "3"  # 저사양 / 노트북 프리셋

    return info


def print_hardware_summary(hw: Dict[str, Any]):
    print("=" * 80)
    print("🖥️ [시스템 하드웨어 자동 감지]")
    print("=" * 80)
    print(f"  • Python 버전   : {hw['python_ver']}")
    print(f"  • 시스템 메모리 : {hw['ram_gb']} GB RAM")
    if hw["has_cuda"] and hw["gpu_name"]:
        print(f"  • 그래픽카드    : {hw['gpu_name']} (VRAM {hw['gpu_vram_gb']} GB, NVIDIA CUDA 가속 지원)")
    else:
        print("  • 그래픽카드    : 외장 NVIDIA GPU 미감지 (내장 그래픽 또는 CPU 연산 모드)")

    if hw["ollama_installed"]:
        print(f"  • Ollama AI 엔진: 정상 감지됨 ({hw['ollama_version']})")
    else:
        print("  • Ollama AI 엔진: ⚠️ 미감지 (고품질 로컬 AI 번역을 위해 설치 권장: https://ollama.com)")

    rec_names = {
        "1": "1번 (🚀 권장 고사양 프리셋 - RTX 4070 Ti / 32GB RAM 최적화)",
        "2": "2번 (⚖️ 표준 밸런스 프리셋 - RTX 3060~4060 / 16GB RAM)",
        "3": "3번 (🍃 저사양 / 노트북 프리셋 - CPU 또는 저사양 GPU / 8GB RAM)",
    }
    print(f"\n  👉 감지 결과 추천: {rec_names.get(hw['recommended_preset'], '1번')}")
    print("=" * 80 + "\n")


def ask_preset_selection(hw: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Prompts user to pick a hardware-tailored preset or manual custom setup."""
    rec = hw["recommended_preset"]

    print("================================================================================")
    print("  [설치 모드 선택] 사용할 PC 사양에 맞는 번호를 선택하세요:")
    print("================================================================================")
    print("  [1] 🚀 권장 고사양 프리셋 (★ 현재 PC 기준: RTX 4070 Ti, 32GB RAM 최적화)")
    print("      • STT 모델 : faster-whisper 'large-v3-turbo' (CUDA float16 초고속)")
    print("      • LLM 모델 : qwen2.5:14b (한/영/중/일 자막 번역 및 구어체 최고 품질)")
    print("      • DB 엔진  : 파일 DB (SQLite - 별도 설치 불필요)")
    print("      • 권장 환경: 12GB+ GPU VRAM, 24GB+ RAM (방송/고화질 자막 최강)")
    print()
    print("  [2] ⚖️ 표준 / 밸런스 프리셋 (RTX 3060 / 4060 등 6~8GB VRAM, 16GB RAM)")
    print("      • STT 모델 : faster-whisper 'large-v3-turbo' (CUDA float16)")
    print("      • LLM 모델 : qwen2.5:7b (매우 빠른 처리 속도와 준수한 번역 품질)")
    print("      • DB 엔진  : 파일 DB (SQLite - 별도 설치 불필요)")
    print("      • 권장 환경: 6~8GB GPU VRAM, 16GB RAM (일반 데스크톱 PC)")
    print()
    print("  [3] 🍃 저사양 / 노트북 프리셋 (GPU 없음 또는 4GB 이하 저사양 GPU, 8GB RAM)")
    print("      • STT 모델 : faster-whisper 'small' (CPU / 저사양 GPU int8 경량 모드)")
    print("      • LLM 모델 : qwen2.5:3b (초경량 고효율 로컬 AI 모델)")
    print("      • DB 엔진  : 파일 DB (SQLite - 별도 설치 불필요)")
    print("      • 권장 환경: 내장 그래픽, 8GB RAM, 사무용 노트북 및 저사양 PC")
    print()
    print("  [4] ⚙️ 고급 사용자 맞춤 설정 (Custom)")
    print("      • DB 종류(SQLite vs PostgreSQL) 및 LLM/Whisper 개별 모델을 직접 지정")
    print("--------------------------------------------------------------------------------")

    prompt_text = f"선택하세요 [기본값: {rec}]: "
    choice = input(prompt_text).strip() or rec

    if choice == "1":
        print("\n>> [1번: 권장 고사양 프리셋]이 선택되었습니다. (Qwen 2.5 14B + Whisper large-v3-turbo)\n")
        return "preset", {
            "DB_TYPE": "sqlite",
            "SQLITE_PATH": "backend/data/transm.db",
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "transm",
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "",
            "OLLAMA_MODEL": "qwen2.5:14b",
            "LLM_BATCH_SIZE": 10,
            "WHISPER_MODEL_SIZE": "large-v3-turbo",
            "WHISPER_DEVICE": "cuda" if hw["has_cuda"] else "cpu",
            "WHISPER_COMPUTE_TYPE": "float16" if hw["has_cuda"] else "int8",
        }
    elif choice == "2":
        print("\n>> [2번: 표준 밸런스 프리셋]이 선택되었습니다. (Qwen 2.5 7B + Whisper large-v3-turbo)\n")
        return "preset", {
            "DB_TYPE": "sqlite",
            "SQLITE_PATH": "backend/data/transm.db",
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "transm",
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "",
            "OLLAMA_MODEL": "qwen2.5:7b",
            "LLM_BATCH_SIZE": 8,
            "WHISPER_MODEL_SIZE": "large-v3-turbo",
            "WHISPER_DEVICE": "cuda" if hw["has_cuda"] else "cpu",
            "WHISPER_COMPUTE_TYPE": "float16" if hw["has_cuda"] else "int8",
        }
    elif choice == "3":
        print("\n>> [3번: 저사양 / 노트북 프리셋]이 선택되었습니다. (Qwen 2.5 3B + Whisper small)\n")
        device = "cuda" if hw["has_cuda"] else "cpu"
        compute_type = "int8_float16" if hw["has_cuda"] else "int8"
        return "preset", {
            "DB_TYPE": "sqlite",
            "SQLITE_PATH": "backend/data/transm.db",
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "transm",
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "",
            "OLLAMA_MODEL": "qwen2.5:3b",
            "LLM_BATCH_SIZE": 5,
            "WHISPER_MODEL_SIZE": "small",
            "WHISPER_DEVICE": device,
            "WHISPER_COMPUTE_TYPE": compute_type,
        }
    else:
        print("\n>> [4번: 사용자 맞춤 설정]으로 진행합니다.\n")
        return "custom", {}


def ask_database_config() -> dict:
    """Manual Step 1: Database selection (SQLite vs PostgreSQL)."""
    print("=" * 80)
    print("[1단계] 데이터베이스(DB) 종류 선택")
    print("=" * 80)
    print("  [1] 파일 DB (SQLite) - ★ 초간단 추천! (별도 DB 프로그램 설치 불필요)")
    print("      -> 프로그램 내부 파일(backend/data/transm.db)에 자동 저장되며 즉시 구동됩니다.")
    print("  [2] 외부 RDB (PostgreSQL) - 대규모 다중 접속 및 기존 PostgreSQL 연동용")
    print("      -> 호스트, 포트, 계정 정보 입력 필요. (미존재 시 DB 자동 생성)")
    print("-" * 80)

    choice = input("선택하세요 [기본값: 1 (SQLite)]: ").strip()
    if choice != "2":
        print("\n>> 파일 DB (SQLite)를 사용합니다. 추가 DB 설치가 필요 없습니다.\n")
        return {
            "DB_TYPE": "sqlite",
            "SQLITE_PATH": "backend/data/transm.db",
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "transm",
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "",
        }

    # PostgreSQL configuration
    print("\n>> PostgreSQL 접속 정보를 입력하세요:")
    host = input("  - 호스트 [기본값: localhost]: ").strip() or "localhost"
    port_str = input("  - 포트 [기본값: 5432]: ").strip() or "5432"
    dbname = input("  - 데이터베이스명 [기본값: transm]: ").strip() or "transm"
    user = input("  - 사용자명 [기본값: postgres]: ").strip() or "postgres"
    password = input("  - 비밀번호 (Enter 시 빈값): ").strip()

    print(f"\n[*] PostgreSQL '{host}:{port_str}' 연결 및 '{dbname}' DB 확인 중...")
    db_created = _try_create_postgres_db(host, int(port_str), user, password, dbname)
    if db_created:
        print(f"[OK] '{dbname}' 데이터베이스가 준비되었습니다.")
    else:
        print(f"[알림] PostgreSQL 직접 연결을 시도했으나 자동 생성을 건너뛰었습니다. (서버 기동 시 재시도)")

    print()
    return {
        "DB_TYPE": "postgres",
        "SQLITE_PATH": "backend/data/transm.db",
        "POSTGRES_HOST": host,
        "POSTGRES_PORT": port_str,
        "POSTGRES_DB": dbname,
        "POSTGRES_USER": user,
        "POSTGRES_PASSWORD": password,
    }


def _try_create_postgres_db(host: str, port: int, user: str, password: str, dbname: str) -> bool:
    """Attempts to connect to PostgreSQL and create dbname if missing."""
    try:
        from sqlalchemy import create_engine, text
        encoded_pw = quote_plus(password)

        target_url = f"postgresql+psycopg2://{user}:{encoded_pw}@{host}:{port}/{dbname}"
        try:
            eng = create_engine(target_url, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            eng.dispose()
            return True
        except Exception:
            pass

        for admin_db in ["postgres", "template1"]:
            admin_url = f"postgresql+psycopg2://{user}:{encoded_pw}@{host}:{port}/{admin_db}"
            try:
                admin_eng = create_engine(admin_url, isolation_level="AUTOCOMMIT")
                with admin_eng.connect() as conn:
                    exists = conn.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                        {"dbname": dbname}
                    ).scalar()
                    if not exists:
                        print(f"[*] '{dbname}' 데이터베이스를 신규 생성합니다...")
                        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
                        print(f"[OK] 데이터베이스 '{dbname}' 생성 완료!")
                admin_eng.dispose()
                return True
            except Exception:
                continue
    except Exception as e:
        print(f"  (PostgreSQL 점검 알림: {e})")
    return False


def ask_llm_model() -> Tuple[str, str, int]:
    """Manual Step 2: Ollama LLM model selection."""
    print("=" * 80)
    print("[2단계] 로컬 AI (LLM) 번역 및 맞춤법 교정 모델 선택")
    print("=" * 80)
    print("  [1] qwen2.5:14b  (★ 강력 추천! 한/영/중/일 자막 번역 및 구어체 최고 품질)")
    print("      - 권장 사양: 시스템 RAM 16GB 이상, GPU VRAM 8GB 이상")
    print("  [2] qwen2.5:7b   (★ 균형 추천! 빠른 속도와 준수한 번역 품질)")
    print("      - 권장 사양: 시스템 RAM 8GB 이상")
    print("  [3] qwen2.5:3b   (🍃 저사양 추천! 저사양 PC 및 노트북 전용 초경량 모델)")
    print("      - 권장 사양: 시스템 RAM 4GB 이상, 내장 그래픽 가능")
    print("  [4] gemma4:12b   (Google 최신 오픈 모델)")
    print("  [5] 직접 모델명 입력 (Custom)")
    print("  [6] 모델 다운로드 건너뛰기")
    print("-" * 80)

    model_map = {
        "1": ("qwen2.5:14b", 10),
        "2": ("qwen2.5:7b", 8),
        "3": ("qwen2.5:3b", 5),
        "4": ("gemma4:12b", 8),
    }

    choice = input("선택하세요 [기본값: 1 (qwen2.5:14b)]: ").strip() or "1"

    if choice in model_map:
        selected_model, batch_size = model_map[choice]
    elif choice == "5":
        selected_model = input("사용할 Ollama 모델명을 입력하세요 (예: llama3.1:8b): ").strip() or "qwen2.5:14b"
        batch_size = 10
    elif choice == "6":
        selected_model = "qwen2.5:14b"
        batch_size = 10
        print(">> 모델 다운로드를 건너뜁니다. (설정값만 저장)\n")
        return selected_model, "http://localhost:11434", batch_size
    else:
        selected_model, batch_size = "qwen2.5:14b", 10

    print(f"\n>> 선택된 모델: {selected_model}")
    _maybe_pull_ollama_model(selected_model)

    return selected_model, "http://localhost:11434", batch_size


def _maybe_pull_ollama_model(model_name: str):
    """Asks user and downloads model via ollama pull if available."""
    if shutil.which("ollama"):
        pull_choice = input(f"지금 Ollama로 '{model_name}' 모델을 다운로드하여 설치하시겠습니까? (Y/n) [기본값: Y]: ").strip().lower()
        if pull_choice in ("", "y", "yes"):
            print(f"\n[*] 'ollama pull {model_name}' 실행 중... (잠시만 기다려주세요)")
            try:
                ret = subprocess.run(["ollama", "pull", model_name], check=False)
                if ret.returncode == 0:
                    print(f"[OK] '{model_name}' 모델 설치가 완료되었습니다!\n")
                else:
                    print(f"⚠️ 모델 다운로드 중 오류가 발생했습니다. 추후 터미널에서 'ollama pull {model_name}'를 직접 실행하실 수 있습니다.\n")
            except Exception as e:
                print(f"⚠️ Ollama 실행 실패: {e}\n")
    else:
        print("⚠️ Ollama가 설치되어 있지 않아 모델 다운로드를 건너뜁니다. 추후 Ollama 설치 후 자동 구동됩니다.\n")


def ask_whisper_config(hw: Dict[str, Any]) -> dict:
    """Manual Step 3: Whisper STT model configuration."""
    print("=" * 80)
    print("[3단계] Whisper 음성 인식(STT) 모델 선택")
    print("=" * 80)
    print("  [1] large-v3-turbo (★ 속도와 정확도 모두 최상, 기본 추천)")
    print("  [2] large-v3       (최고 정확도, 다소 무거움)")
    print("  [3] medium         (중간 성능, 밸런스형)")
    print("  [4] small          (🍃 저사양 PC / 노트북용, 가벼움)")
    print("  [5] base           (초경량, 테스트용)")
    print("-" * 80)

    whisper_map = {
        "1": "large-v3-turbo",
        "2": "large-v3",
        "3": "medium",
        "4": "small",
        "5": "base",
    }
    choice = input("선택하세요 [기본값: 1 (large-v3-turbo)]: ").strip() or "1"
    model_size = whisper_map.get(choice, "large-v3-turbo")

    if hw["has_cuda"]:
        device = "cuda"
        compute_type = "float16"
        print(f">> NVIDIA GPU 가속(CUDA, {compute_type})이 감지되어 자동 적용됩니다.\n")
    else:
        device = "cpu"
        compute_type = "int8"
        print(f">> GPU를 찾을 수 없어 CPU 모드({compute_type})로 설정됩니다.\n")

    return {
        "WHISPER_MODEL_SIZE": model_size,
        "WHISPER_DEVICE": device,
        "WHISPER_COMPUTE_TYPE": compute_type,
    }


def write_env_file(config: dict):
    """Writes accumulated configurations to .env file."""
    if ENV_FILE.exists():
        backup_file = ROOT_DIR / ".env.bak"
        try:
            shutil.copyfile(ENV_FILE, backup_file)
            print(f"[*] 기존 .env 파일이 백업되었습니다: {backup_file.name}")
        except Exception:
            pass

    content = f"""# ==============================================================================
# TransM - AI Subtitle Studio Environment Configuration
# Automatically generated by setup_wizard.py
# ==============================================================================

# Server Network Config
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# Database Configuration ('sqlite' or 'postgres')
DB_TYPE={config.get("DB_TYPE", "sqlite")}
SQLITE_PATH={config.get("SQLITE_PATH", "backend/data/transm.db")}

# PostgreSQL Database Settings (Used when DB_TYPE=postgres)
POSTGRES_HOST={config.get("POSTGRES_HOST", "localhost")}
POSTGRES_PORT={config.get("POSTGRES_PORT", "5432")}
POSTGRES_DB={config.get("POSTGRES_DB", "transm")}
POSTGRES_USER={config.get("POSTGRES_USER", "postgres")}
POSTGRES_PASSWORD={config.get("POSTGRES_PASSWORD", "")}

# Local LLM Service (Ollama)
OLLAMA_HOST={config.get("OLLAMA_HOST", "http://localhost:11434")}
OLLAMA_MODEL={config.get("OLLAMA_MODEL", "qwen2.5:14b")}
LLM_BATCH_SIZE={config.get("LLM_BATCH_SIZE", 10)}

# Whisper Speech-to-Text Engine
WHISPER_MODEL_SIZE={config.get("WHISPER_MODEL_SIZE", "large-v3-turbo")}
WHISPER_DEVICE={config.get("WHISPER_DEVICE", "cuda")}
WHISPER_COMPUTE_TYPE={config.get("WHISPER_COMPUTE_TYPE", "float16")}

# Media Scan Root Directories (Server-side search)
MEDIA_SCAN_DIRS=D:\\Videos,D:\\Media
"""
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[OK] 환경설정 파일(.env)이 성공적으로 생성되었습니다!")


def main():
    print_banner()

    # Step 0: Auto-detect hardware
    hw_info = detect_system_hardware()
    print_hardware_summary(hw_info)

    # Step 1: Preset selection (High / Balanced / Low-spec / Custom)
    mode, preset_config = ask_preset_selection(hw_info)

    if mode == "preset":
        # Prompt for Ollama pull for the chosen preset model
        model_name = preset_config.get("OLLAMA_MODEL", "qwen2.5:14b")
        _maybe_pull_ollama_model(model_name)

        final_config = {
            **preset_config,
            "OLLAMA_HOST": "http://localhost:11434",
        }
    else:
        # Custom manual step-by-step
        db_config = ask_database_config()
        llm_model, ollama_host, batch_size = ask_llm_model()
        whisper_config = ask_whisper_config(hw_info)

        final_config = {
            **db_config,
            "OLLAMA_HOST": ollama_host,
            "OLLAMA_MODEL": llm_model,
            "LLM_BATCH_SIZE": batch_size,
            **whisper_config,
        }

    # Step 4: Write .env
    write_env_file(final_config)

    print("\n" + "=" * 80)
    print("🎉 TransM 초기 환경 설정이 성공적으로 완료되었습니다!")
    print("=" * 80)
    print("  [실행 방법]")
    print("  1. 'start.bat' 파일을 더블클릭하면 전체 시스템이 자동으로 실행됩니다.")
    print("  2. 웹 브라우저에서 'http://localhost:8000' (또는 http://localhost:5173)으로 접속하세요.")
    print("  3. 설정을 변경하고 싶다면 언제든지 'python setup_wizard.py'를 다시 실행할 수 있습니다.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
