#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TransM - Standalone Database Initializer
Creates and verifies all database tables in SQLite or PostgreSQL.
"""

import sys
from pathlib import Path

# Add backend directory to sys.path
INSTALL_DIR = Path(__file__).resolve().parent
ROOT_DIR = INSTALL_DIR.parent
BACKEND_DIR = ROOT_DIR / "backend"

sys.path.insert(0, str(BACKEND_DIR))

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_init_database() -> bool:
    try:
        from app.database import get_engine, init_db, is_sqlite_db
        from sqlalchemy import text

        print("[*] 데이터베이스 연결 및 테이블 초기화 시작...")
        engine = get_engine()
        is_sqlite = is_sqlite_db()
        db_label = "SQLite 파일 DB" if is_sqlite else "PostgreSQL DB"

        print(f"[*] 활성 데이터베이스 타입: {db_label}")
        init_db()

        # 무결성 검증: 핵심 4개 테이블 존재 확인
        required_tables = ["transm_tasks", "completed_tasks", "studio_queue_items", "proper_noun_dictionary"]
        with engine.connect() as conn:
            if is_sqlite:
                rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table';")).fetchall()
                existing = {r[0] for r in rows}
            else:
                rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public';")).fetchall()
                existing = {r[0] for r in rows}

        missing = [t for t in required_tables if t not in existing]
        if missing:
            print(f"[ERROR] 테이블 초기화 후 일부 테이블이 누락되었습니다: {missing}")
            return False

        print(f"[OK] {db_label} 내 모든 테이블({', '.join(required_tables)})이 정상 생성 및 검증되었습니다!")
        return True
    except Exception as e:
        print(f"[ERROR] 데이터베이스 테이블 생성 실패: {e}")
        return False


if __name__ == "__main__":
    success = run_init_database()
    sys.exit(0 if success else 1)
