import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
from app.config import (
    DB_TYPE,
    SQLITE_PATH,
    DATABASE_URL,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_DB,
    POSTGRES_USER,
    POSTGRES_PASSWORD,
    DATA_DIR,
)

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_connected_db_name: Optional[str] = None
_is_sqlite: bool = False


def is_sqlite_db() -> bool:
    """Returns True if the active database is SQLite."""
    global _is_sqlite
    return _is_sqlite


def _configure_sqlite_pragma(engine: Engine):
    """Configures SQLite connection settings for high concurrency and performance."""
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()


def _ensure_postgres_db(host: str, port: int, user: str, password: str, target_db: str) -> bool:
    """
    Attempts to connect to admin DB ('postgres' or 'template1')
    and creates target_db automatically if it does not already exist.
    """
    admin_dbs = ["postgres", "template1"]
    encoded_pw = quote_plus(password)
    for admin_db in admin_dbs:
        admin_url = f"postgresql+psycopg2://{user}:{encoded_pw}@{host}:{port}/{admin_db}"
        try:
            admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
            with admin_engine.connect() as conn:
                exists = conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                    {"dbname": target_db}
                ).scalar()
                if not exists:
                    logger.info(f"Target PostgreSQL database '{target_db}' does not exist. Creating it now...")
                    conn.execute(text(f'CREATE DATABASE "{target_db}"'))
                    logger.info(f"PostgreSQL database '{target_db}' created successfully.")
            admin_engine.dispose()
            return True
        except Exception as e:
            logger.debug(f"Could not check/create db via {admin_db}: {e}")
    return False


def get_engine() -> Engine:
    """Initializes and returns a pooled SQLAlchemy Engine with SQLite & PostgreSQL support."""
    global _engine, _connected_db_name, _is_sqlite
    if _engine is not None:
        return _engine

    # 1. Custom DATABASE_URL explicitly configured
    if DATABASE_URL:
        if DATABASE_URL.startswith("sqlite"):
            _is_sqlite = True
            _engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
            _configure_sqlite_pragma(_engine)
            _connected_db_name = DATABASE_URL
            logger.info(f"Connected to custom SQLite database via DATABASE_URL: {DATABASE_URL}")
            return _engine
        else:
            _is_sqlite = False
            _engine = create_engine(
                DATABASE_URL,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=1800,
            )
            _connected_db_name = DATABASE_URL
            logger.info(f"Connected to custom database via DATABASE_URL")
            return _engine

    # 2. SQLite mode (default out-of-the-box zero-config mode)
    if DB_TYPE == "sqlite":
        _is_sqlite = True
        sqlite_file = Path(SQLITE_PATH).resolve()
        sqlite_file.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{sqlite_file.as_posix()}"
        _engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
        )
        _configure_sqlite_pragma(_engine)
        _connected_db_name = str(sqlite_file)
        logger.info(f"Connected to SQLite file database: {sqlite_file}")
        return _engine

    # 3. PostgreSQL mode
    _is_sqlite = False
    encoded_pw = quote_plus(POSTGRES_PASSWORD)

    # Attempt to create database if it doesn't exist
    try:
        _ensure_postgres_db(POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB)
    except Exception as e:
        logger.warning(f"Failed PostgreSQL auto-creation check: {e}")

    db_candidates = [POSTGRES_DB]
    if "text" not in db_candidates:
        db_candidates.append("text")

    last_error = None
    for candidate_db in db_candidates:
        db_url = f"postgresql+psycopg2://{POSTGRES_USER}:{encoded_pw}@{POSTGRES_HOST}:{POSTGRES_PORT}/{candidate_db}"
        try:
            temp_engine = create_engine(
                db_url,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=1800,
            )
            with temp_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            _engine = temp_engine
            _connected_db_name = candidate_db
            logger.info(f"Connected to PostgreSQL database '{candidate_db}' on {POSTGRES_HOST}:{POSTGRES_PORT}")
            return _engine
        except Exception as e:
            last_error = e
            logger.warning(f"Could not connect to PostgreSQL database '{candidate_db}': {e}")

    logger.error(
        f"PostgreSQL connection to {POSTGRES_HOST}:{POSTGRES_PORT} failed ({last_error}). "
        f"Falling back gracefully to local SQLite database: {SQLITE_PATH}"
    )
    _is_sqlite = True
    sqlite_file = Path(SQLITE_PATH).resolve()
    sqlite_file.parent.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{sqlite_file.as_posix()}"
    _engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
    )
    _configure_sqlite_pragma(_engine)
    _connected_db_name = str(sqlite_file)
    return _engine


def init_db():
    """Initializes schema and tables in SQLite or PostgreSQL."""
    engine = get_engine()
    is_sqlite = is_sqlite_db()

    json_type = "TEXT" if is_sqlite else "JSONB"
    timestamp_type = "TIMESTAMP" if is_sqlite else "TIMESTAMP WITH TIME ZONE"
    serial_pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"

    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS transm_tasks (
        task_id VARCHAR(64) PRIMARY KEY,
        filename VARCHAR(255) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'PROCESSING',
        stage TEXT,
        progress INTEGER NOT NULL DEFAULT 0,
        video_path TEXT,
        audio_path TEXT,
        srt_path TEXT,
        srt_download_url TEXT,
        raw_segments {json_type},
        checkpoint_segments {json_type},
        subtitles {json_type},
        error TEXT,
        created_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP,
        updated_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_transm_tasks_created_at ON transm_tasks (created_at);

    CREATE TABLE IF NOT EXISTS completed_tasks (
        task_id VARCHAR(64) PRIMARY KEY,
        filename VARCHAR(255) NOT NULL,
        subtitle_count INTEGER NOT NULL DEFAULT 0,
        srt_path TEXT,
        srt_download_url TEXT,
        task_type VARCHAR(32) NOT NULL DEFAULT 'studio',
        completed_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP,
        download_count INTEGER DEFAULT 0,
        last_downloaded_at {timestamp_type}
    );
    CREATE INDEX IF NOT EXISTS idx_completed_tasks_at ON completed_tasks (completed_at);
    CREATE INDEX IF NOT EXISTS idx_completed_tasks_type ON completed_tasks (task_type);

    CREATE TABLE IF NOT EXISTS studio_queue_items (
        id VARCHAR(64) PRIMARY KEY,
        filename VARCHAR(255) NOT NULL,
        size BIGINT DEFAULT 0,
        status VARCHAR(32) NOT NULL DEFAULT 'WAITING',
        upload_progress INTEGER DEFAULT 0,
        task_id VARCHAR(64),
        error TEXT,
        order_index INTEGER DEFAULT 0,
        client_id VARCHAR(64),
        added_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP,
        updated_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_studio_queue_order ON studio_queue_items (order_index, added_at);

    CREATE TABLE IF NOT EXISTS proper_noun_dictionary (
        id {serial_pk},
        source_word VARCHAR(255) NOT NULL,
        target_word VARCHAR(255) NOT NULL,
        notes TEXT,
        created_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP,
        updated_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_dict_source ON proper_noun_dictionary (source_word);
    """
    with engine.begin() as conn:
        for stmt in create_table_sql.strip().split(";"):
            cleaned = stmt.strip()
            if cleaned:
                conn.execute(text(cleaned))

    # Migration for completed_tasks columns if table was created by an older version
    if is_sqlite:
        with engine.begin() as conn:
            existing_cols = {col[1] for col in conn.execute(text("PRAGMA table_info(completed_tasks)")).fetchall()}
            if "task_type" not in existing_cols:
                conn.execute(text("ALTER TABLE completed_tasks ADD COLUMN task_type VARCHAR(32) DEFAULT 'studio'"))
            if "download_count" not in existing_cols:
                conn.execute(text("ALTER TABLE completed_tasks ADD COLUMN download_count INTEGER DEFAULT 0"))
            if "last_downloaded_at" not in existing_cols:
                conn.execute(text("ALTER TABLE completed_tasks ADD COLUMN last_downloaded_at TIMESTAMP"))
    else:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE completed_tasks ADD COLUMN IF NOT EXISTS task_type VARCHAR(32) DEFAULT 'studio';"))
            conn.execute(text("ALTER TABLE completed_tasks ADD COLUMN IF NOT EXISTS download_count INTEGER DEFAULT 0;"))
            conn.execute(text("ALTER TABLE completed_tasks ADD COLUMN IF NOT EXISTS last_downloaded_at TIMESTAMP WITH TIME ZONE;"))

    # Update task_type for existing records (Compatible with both SQLite and PostgreSQL)
    with engine.begin() as conn:
        conn.execute(text("""
        UPDATE completed_tasks
        SET task_type = 'studio'
        WHERE LOWER(filename) LIKE '%.mp4' 
           OR LOWER(filename) LIKE '%.mkv' 
           OR LOWER(filename) LIKE '%.avi' 
           OR LOWER(filename) LIKE '%.mov' 
           OR LOWER(filename) LIKE '%.wmv' 
           OR LOWER(filename) LIKE '%.flv' 
           OR LOWER(filename) LIKE '%.ts' 
           OR LOWER(filename) LIKE '%.webm';
        """))
        conn.execute(text("""
        UPDATE completed_tasks
        SET task_type = 'translator'
        WHERE LOWER(filename) LIKE '%.srt' AND (task_type IS NULL OR task_type = 'studio');
        """))

    # Synchronize any completed tasks from transm_tasks that are not yet in completed_tasks
    if not is_sqlite:
        with engine.begin() as conn:
            conn.execute(text("""
            INSERT INTO completed_tasks (
                task_id, filename, subtitle_count, srt_path, srt_download_url, task_type, completed_at, download_count
            )
            SELECT 
                t.task_id,
                t.filename,
                COALESCE(jsonb_array_length(CASE WHEN jsonb_typeof(t.subtitles) = 'array' THEN t.subtitles ELSE '[]'::jsonb END), 0) AS subtitle_count,
                t.srt_path,
                t.srt_download_url,
                CASE WHEN LOWER(t.filename) LIKE '%.srt' THEN 'translator' ELSE 'studio' END AS task_type,
                COALESCE(t.updated_at, CURRENT_TIMESTAMP) AS completed_at,
                0 AS download_count
            FROM transm_tasks t
            WHERE t.status = 'COMPLETED'
              AND NOT EXISTS (
                  SELECT 1 FROM completed_tasks c WHERE c.task_id = t.task_id
              );
            """))
    else:
        with engine.begin() as conn:
            missing_tasks = conn.execute(text("""
                SELECT t.task_id, t.filename, t.subtitles, t.srt_path, t.srt_download_url, t.updated_at
                FROM transm_tasks t
                WHERE t.status = 'COMPLETED'
                  AND NOT EXISTS (
                      SELECT 1 FROM completed_tasks c WHERE c.task_id = t.task_id
                  );
            """)).fetchall()
            for r in missing_tasks:
                sub_count = 0
                if r[2]:
                    try:
                        subs = json.loads(r[2]) if isinstance(r[2], str) else r[2]
                        if isinstance(subs, list):
                            sub_count = len(subs)
                    except Exception:
                        pass
                fn = (r[1] or "").lower()
                ttype = "translator" if fn.endswith(".srt") else "studio"
                conn.execute(text("""
                    INSERT INTO completed_tasks (
                        task_id, filename, subtitle_count, srt_path, srt_download_url, task_type, completed_at, download_count
                    ) VALUES (
                        :tid, :fn, :sc, :sp, :sdu, :tt, COALESCE(:upd, CURRENT_TIMESTAMP), 0
                    )
                """), {
                    "tid": r[0], "fn": r[1], "sc": sub_count, "sp": r[3], "sdu": r[4], "tt": ttype, "upd": r[5]
                })

    logger.info(f"Database initialized successfully ({'SQLite' if is_sqlite else 'PostgreSQL'}): tables are ready.")


def upsert_task(
    task_id: str,
    filename: str,
    status: str,
    stage: str,
    progress: int,
    video_path: Optional[str] = None,
    audio_path: Optional[str] = None,
    srt_path: Optional[str] = None,
    srt_download_url: Optional[str] = None,
    error: Optional[str] = None,
):
    """Inserts a new task or updates progress/stage/status of an existing task."""
    engine = get_engine()
    sql = """
    INSERT INTO transm_tasks (
        task_id, filename, status, stage, progress,
        video_path, audio_path, srt_path, srt_download_url, error, updated_at
    ) VALUES (
        :task_id, :filename, :status, :stage, :progress,
        :video_path, :audio_path, :srt_path, :srt_download_url, :error, CURRENT_TIMESTAMP
    )
    ON CONFLICT (task_id) DO UPDATE SET
        filename = EXCLUDED.filename,
        status = EXCLUDED.status,
        stage = EXCLUDED.stage,
        progress = EXCLUDED.progress,
        video_path = COALESCE(EXCLUDED.video_path, transm_tasks.video_path),
        audio_path = COALESCE(EXCLUDED.audio_path, transm_tasks.audio_path),
        srt_path = COALESCE(EXCLUDED.srt_path, transm_tasks.srt_path),
        srt_download_url = COALESCE(EXCLUDED.srt_download_url, transm_tasks.srt_download_url),
        error = EXCLUDED.error,
        updated_at = CURRENT_TIMESTAMP;
    """
    with engine.begin() as conn:
        conn.execute(text(sql), {
            "task_id": task_id,
            "filename": filename,
            "status": status,
            "stage": stage,
            "progress": progress,
            "video_path": video_path,
            "audio_path": audio_path,
            "srt_path": srt_path,
            "srt_download_url": srt_download_url,
            "error": error,
        })


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves full task record from database."""
    engine = get_engine()
    sql = "SELECT * FROM transm_tasks WHERE task_id = :task_id"
    with engine.connect() as conn:
        result = conn.execute(text(sql), {"task_id": task_id}).mappings().first()
        if not result:
            return None
        return dict(result)


def save_raw_segments(task_id: str, raw_segments: List[Dict[str, Any]]):
    """Saves raw Whisper STT segments (timestamps & text) into database."""
    engine = get_engine()
    sql = """
    UPDATE transm_tasks
    SET raw_segments = :raw_segments, updated_at = CURRENT_TIMESTAMP
    WHERE task_id = :task_id;
    """
    with engine.begin() as conn:
        conn.execute(text(sql), {
            "task_id": task_id,
            "raw_segments": json.dumps(raw_segments, ensure_ascii=False)
        })


def get_raw_segments(task_id: str) -> Optional[List[Dict[str, Any]]]:
    """Retrieves cached raw Whisper STT segments if previously saved."""
    engine = get_engine()
    sql = "SELECT raw_segments FROM transm_tasks WHERE task_id = :task_id"
    with engine.connect() as conn:
        row = conn.execute(text(sql), {"task_id": task_id}).scalar()
        if row is None:
            return None
        if isinstance(row, str):
            try:
                return json.loads(row)
            except Exception:
                return None
        return row


def save_checkpoint_segments(task_id: str, checkpoint_map: Dict[int, str]):
    """Saves LLM refined segments batch-by-batch for crash resilience."""
    engine = get_engine()
    # Convert integer keys to strings for JSON serialization
    serialized_map = {str(k): v for k, v in checkpoint_map.items()}
    sql = """
    UPDATE transm_tasks
    SET checkpoint_segments = :checkpoint_segments, updated_at = CURRENT_TIMESTAMP
    WHERE task_id = :task_id;
    """
    with engine.begin() as conn:
        conn.execute(text(sql), {
            "task_id": task_id,
            "checkpoint_segments": json.dumps(serialized_map, ensure_ascii=False)
        })


def get_checkpoint_segments(task_id: str) -> Optional[Dict[int, str]]:
    """Retrieves existing LLM refined segments checkpoint to resume work."""
    engine = get_engine()
    sql = "SELECT checkpoint_segments FROM transm_tasks WHERE task_id = :task_id"
    with engine.connect() as conn:
        row = conn.execute(text(sql), {"task_id": task_id}).scalar()
        if row is None:
            return None
        try:
            raw_dict = json.loads(row) if isinstance(row, str) else row
            return {int(k): v for k, v in raw_dict.items()}
        except Exception:
            return None


def save_subtitles(task_id: str, subtitles: List[Dict[str, Any]]):
    """Saves final or user-edited subtitle list."""
    engine = get_engine()
    sql = """
    UPDATE transm_tasks
    SET subtitles = :subtitles, updated_at = CURRENT_TIMESTAMP
    WHERE task_id = :task_id;
    """
    with engine.begin() as conn:
        conn.execute(text(sql), {
            "task_id": task_id,
            "subtitles": json.dumps(subtitles, ensure_ascii=False)
        })


def get_all_tasks(limit: int = 50) -> List[Dict[str, Any]]:
    """Returns list of recent tasks sorted by creation date."""
    engine = get_engine()
    sql = """
    SELECT task_id, filename, status, stage, progress, srt_download_url, error, created_at, updated_at
    FROM transm_tasks
    ORDER BY created_at DESC
    LIMIT :limit
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"limit": limit}).mappings().all()
        return [dict(r) for r in rows]


def add_completed_task(
    task_id: str,
    filename: str,
    subtitle_count: int,
    srt_path: Optional[str] = None,
    srt_download_url: Optional[str] = None,
    task_type: str = "studio"
):
    """Records or updates a completed subtitle generation task in database."""
    engine = get_engine()
    sql = """
    INSERT INTO completed_tasks (
        task_id, filename, subtitle_count, srt_path, srt_download_url, task_type, completed_at
    ) VALUES (
        :task_id, :filename, :subtitle_count, :srt_path, :srt_download_url, :task_type, CURRENT_TIMESTAMP
    )
    ON CONFLICT (task_id) DO UPDATE SET
        filename = EXCLUDED.filename,
        subtitle_count = EXCLUDED.subtitle_count,
        srt_path = EXCLUDED.srt_path,
        srt_download_url = EXCLUDED.srt_download_url,
        task_type = EXCLUDED.task_type,
        completed_at = CURRENT_TIMESTAMP;
    """
    with engine.begin() as conn:
        conn.execute(text(sql), {
            "task_id": task_id,
            "filename": filename,
            "subtitle_count": subtitle_count,
            "srt_path": srt_path,
            "srt_download_url": srt_download_url or f"/api/download/{task_id}",
            "task_type": task_type
        })


def increment_download_count(task_id: str) -> int:
    """Increments the download count for a completed task and updates timestamp."""
    engine = get_engine()
    sql_update = """
    UPDATE completed_tasks
    SET download_count = COALESCE(download_count, 0) + 1,
        last_downloaded_at = CURRENT_TIMESTAMP
    WHERE task_id = :task_id;
    """
    sql_select = "SELECT download_count FROM completed_tasks WHERE task_id = :task_id;"
    try:
        with engine.begin() as conn:
            conn.execute(text(sql_update), {"task_id": task_id})
            res = conn.execute(text(sql_select), {"task_id": task_id}).scalar()
            return int(res or 1)
    except Exception as e:
        logger.warning(f"Error incrementing download count for {task_id}: {e}")
        return 1


def get_completed_tasks(
    limit: int = 10000,
    task_type: Optional[str] = None,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Returns list of completed tasks ordered by completion date, optionally filtered by task_type."""
    engine = get_engine()
    if task_type:
        sql = """
        SELECT task_id, filename, subtitle_count, srt_path, srt_download_url, task_type, completed_at, download_count, last_downloaded_at
        FROM completed_tasks
        WHERE task_type = :task_type
        ORDER BY completed_at DESC
        LIMIT :limit OFFSET :offset;
        """
        params = {"limit": limit, "task_type": task_type, "offset": offset}
    else:
        sql = """
        SELECT task_id, filename, subtitle_count, srt_path, srt_download_url, task_type, completed_at, download_count, last_downloaded_at
        FROM completed_tasks
        ORDER BY completed_at DESC
        LIMIT :limit OFFSET :offset;
        """
        params = {"limit": limit, "offset": offset}

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        result = []
        for r in rows:
            row_dict = dict(r)
            if row_dict.get("completed_at"):
                row_dict["completed_at"] = (
                    row_dict["completed_at"].isoformat()
                    if hasattr(row_dict["completed_at"], "isoformat")
                    else str(row_dict["completed_at"])
                )
            if row_dict.get("last_downloaded_at"):
                row_dict["last_downloaded_at"] = (
                    row_dict["last_downloaded_at"].isoformat()
                    if hasattr(row_dict["last_downloaded_at"], "isoformat")
                    else str(row_dict["last_downloaded_at"])
                )
            row_dict["download_count"] = int(row_dict.get("download_count") or 0)
            row_dict["downloaded"] = row_dict["download_count"] > 0
            if not row_dict.get("task_type"):
                fn = (row_dict.get("filename") or "").lower()
                if fn.endswith(".srt"):
                    row_dict["task_type"] = "translator"
                else:
                    row_dict["task_type"] = "studio"
            result.append(row_dict)
        return result


def delete_task(task_id: str) -> bool:
    """Deletes task record from both completed_tasks and transm_tasks tables."""
    engine = get_engine()
    sql_completed = "DELETE FROM completed_tasks WHERE task_id = :task_id;"
    sql_tasks = "DELETE FROM transm_tasks WHERE task_id = :task_id;"
    with engine.begin() as conn:
        conn.execute(text(sql_completed), {"task_id": task_id})
        conn.execute(text(sql_tasks), {"task_id": task_id})
    logger.info(f"Deleted task {task_id} from database.")
    return True


def delete_tasks_batch(task_ids: List[str]) -> List[str]:
    """Deletes a list of task IDs from both completed_tasks and transm_tasks in batch (Cross-DB compatible)."""
    if not task_ids:
        return []
    clean_ids = [str(tid) for tid in task_ids if tid]
    if not clean_ids:
        return []
    engine = get_engine()
    placeholders = [f":id_{i}" for i in range(len(clean_ids))]
    params = {f"id_{i}": tid for i, tid in enumerate(clean_ids)}
    in_clause = ",".join(placeholders)
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM completed_tasks WHERE task_id IN ({in_clause});"), params)
        conn.execute(text(f"DELETE FROM transm_tasks WHERE task_id IN ({in_clause});"), params)
    logger.info(f"Deleted {len(clean_ids)} tasks from database in batch.")
    return clean_ids


def delete_all_tasks(task_type: Optional[str] = None) -> List[str]:
    """
    Deletes all tasks from DB (optionally filtered by task_type).
    Returns list of deleted task_ids so the caller can purge their files.
    """
    engine = get_engine()
    with engine.begin() as conn:
        if task_type and task_type in ("studio", "translator"):
            res = conn.execute(text("SELECT task_id FROM completed_tasks WHERE task_type = :tt;"), {"tt": task_type})
            ids = [str(r[0]) for r in res.fetchall()]
            if ids:
                placeholders = [f":id_{i}" for i in range(len(ids))]
                params = {f"id_{i}": tid for i, tid in enumerate(ids)}
                params["tt"] = task_type
                in_clause = ",".join(placeholders)
                conn.execute(text("DELETE FROM completed_tasks WHERE task_type = :tt;"), {"tt": task_type})
                conn.execute(text(f"DELETE FROM transm_tasks WHERE task_id IN ({in_clause});"), params)
            logger.info(f"Deleted all {len(ids)} {task_type} tasks from database.")
            return ids
        else:
            res = conn.execute(text("SELECT task_id FROM completed_tasks;"))
            ids = [str(r[0]) for r in res.fetchall()]
            conn.execute(text("DELETE FROM completed_tasks;"))
            conn.execute(text("DELETE FROM transm_tasks;"))
            logger.info(f"Deleted all {len(ids)} tasks from database.")
            return ids


def get_studio_queue() -> List[Dict[str, Any]]:
    """Retrieves all active/waiting/recent items from studio_queue_items."""
    engine = get_engine()
    sql = """
    SELECT id, filename, size, status, upload_progress, task_id, error, order_index, client_id, added_at, updated_at
    FROM studio_queue_items
    ORDER BY order_index ASC, added_at ASC;
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
            items = []
            for r in rows:
                row_dict = dict(r._mapping)
                if row_dict.get("added_at"):
                    row_dict["added_at"] = (
                        row_dict["added_at"].isoformat()
                        if hasattr(row_dict["added_at"], "isoformat")
                        else str(row_dict["added_at"])
                    )
                if row_dict.get("updated_at"):
                    row_dict["updated_at"] = (
                        row_dict["updated_at"].isoformat()
                        if hasattr(row_dict["updated_at"], "isoformat")
                        else str(row_dict["updated_at"])
                    )
                items.append(row_dict)
            return items
    except Exception as e:
        logger.warning(f"Error fetching studio_queue_items: {e}")
        return []


def upsert_studio_queue_items(items: List[Dict[str, Any]], client_id: Optional[str] = None) -> bool:
    """Upserts a list of queue items into studio_queue_items. Completed items are automatically removed."""
    if not items:
        return True
    engine = get_engine()
    sql = """
    INSERT INTO studio_queue_items (id, filename, size, status, upload_progress, task_id, error, order_index, client_id, updated_at)
    VALUES (:id, :filename, :size, :status, :upload_progress, :task_id, :error, :order_index, :client_id, CURRENT_TIMESTAMP)
    ON CONFLICT (id) DO UPDATE SET
        filename = EXCLUDED.filename,
        size = EXCLUDED.size,
        status = CASE 
            WHEN studio_queue_items.status = 'WAITING' AND studio_queue_items.task_id IS NULL AND EXCLUDED.status = 'COMPLETED'
            THEN 'WAITING'
            WHEN studio_queue_items.status IN ('PROCESSING', 'COMPLETED', 'FAILED') AND EXCLUDED.status = 'WAITING' 
            THEN studio_queue_items.status 
            ELSE EXCLUDED.status 
        END,
        upload_progress = CASE 
            WHEN studio_queue_items.status = 'WAITING' AND studio_queue_items.task_id IS NULL AND EXCLUDED.status = 'COMPLETED'
            THEN 0
            WHEN studio_queue_items.status IN ('PROCESSING', 'COMPLETED') 
            THEN 100 
            ELSE EXCLUDED.upload_progress 
        END,
        task_id = CASE
            WHEN studio_queue_items.status = 'WAITING' AND studio_queue_items.task_id IS NULL AND EXCLUDED.status = 'COMPLETED'
            THEN NULL
            ELSE COALESCE(studio_queue_items.task_id, EXCLUDED.task_id)
        END,
        error = COALESCE(EXCLUDED.error, studio_queue_items.error),
        order_index = EXCLUDED.order_index,
        client_id = COALESCE(EXCLUDED.client_id, studio_queue_items.client_id),
        updated_at = CURRENT_TIMESTAMP;
    """
    try:
        with engine.begin() as conn:
            for idx, it in enumerate(items):
                item_id = str(it.get("id"))
                item_status = str(it.get("status") or "WAITING")
                if item_status == "COMPLETED":
                    conn.execute(
                        text("DELETE FROM studio_queue_items WHERE id = :id AND NOT (status = 'WAITING' AND task_id IS NULL);"),
                        {"id": item_id}
                    )
                    continue

                params = {
                    "id": item_id,
                    "filename": str(it.get("filename") or ""),
                    "size": int(it.get("size") or 0),
                    "status": item_status,
                    "upload_progress": int(it.get("upload_progress") if it.get("upload_progress") is not None else (it.get("uploadProgress") or 0)),
                    "task_id": it.get("task_id") or it.get("taskId"),
                    "error": it.get("error"),
                    "order_index": int(it.get("order_index") if it.get("order_index") is not None else idx),
                    "client_id": client_id or it.get("client_id") or it.get("clientId") or ""
                }
                conn.execute(text(sql), params)
        return True
    except Exception as e:
        logger.warning(f"Error upserting studio_queue_items: {e}")
        return False


def delete_studio_queue_item(item_id: str) -> bool:
    """Deletes an item from studio_queue_items."""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM studio_queue_items WHERE id = :id;"), {"id": item_id})
        return True
    except Exception as e:
        logger.warning(f"Error deleting studio_queue_item {item_id}: {e}")
        return False


def delete_studio_queue_by_task_id(task_id: str, filename: Optional[str] = None) -> bool:
    """Deletes a completed queue item from studio_queue_items by task_id (or fallback by filename)."""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            res = conn.execute(text("DELETE FROM studio_queue_items WHERE task_id = :task_id;"), {"task_id": task_id})
            if res.rowcount == 0 and filename:
                conn.execute(
                    text("""
                    DELETE FROM studio_queue_items
                    WHERE id = (
                        SELECT id FROM studio_queue_items
                        WHERE filename = :filename
                        ORDER BY order_index ASC, added_at ASC
                        LIMIT 1
                    );
                    """),
                    {"filename": filename}
                )
        return True
    except Exception as e:
        logger.warning(f"Error deleting studio_queue_item for task {task_id}: {e}")
        return False


def clear_completed_studio_queue() -> bool:
    """Clears completed and failed items from studio_queue_items."""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM studio_queue_items WHERE status IN ('COMPLETED', 'FAILED');"))
        return True
    except Exception as e:
        logger.warning(f"Error clearing completed studio_queue_items: {e}")
        return False


def update_queue_status_by_task_id(task_id: str, status: str, error: Optional[str] = None, filename: Optional[str] = None) -> bool:
    """Updates status of a queue item associated with a specific task_id (or removes it if COMPLETED)."""
    if status == "COMPLETED":
        return delete_studio_queue_by_task_id(task_id, filename=filename)

    engine = get_engine()
    sql = """
    UPDATE studio_queue_items
    SET status = :status, error = :error, updated_at = CURRENT_TIMESTAMP
    WHERE task_id = :task_id;
    """
    try:
        with engine.begin() as conn:
            res = conn.execute(text(sql), {"task_id": task_id, "status": status, "error": error})
            if res.rowcount == 0 and filename:
                conn.execute(
                    text("""
                    UPDATE studio_queue_items
                    SET task_id = :task_id, status = :status, error = :error, updated_at = CURRENT_TIMESTAMP
                    WHERE id = (
                        SELECT id FROM studio_queue_items
                        WHERE filename = :filename AND status IN ('PROCESSING', 'UPLOADING', 'WAITING')
                        ORDER BY order_index ASC, added_at ASC
                        LIMIT 1
                    );
                    """),
                    {"task_id": task_id, "status": status, "error": error, "filename": filename}
                )
        return True
    except Exception as e:
        logger.warning(f"Error updating queue status for task {task_id}: {e}")
        return False


def update_queue_item_task_link(queue_id: str, task_id: str, status: str = "PROCESSING") -> bool:
    """Links task_id to a queue item and updates its status and upload_progress."""
    engine = get_engine()
    sql = """
    UPDATE studio_queue_items
    SET task_id = :task_id, status = :status, upload_progress = 100, updated_at = CURRENT_TIMESTAMP
    WHERE id = :id;
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(sql), {"id": queue_id, "task_id": task_id, "status": status})
        return True
    except Exception as e:
        logger.warning(f"Error linking task {task_id} to queue item {queue_id}: {e}")
        return False


def link_queue_item_by_filename(filename: str, task_id: str, status: str = "PROCESSING") -> bool:
    """Finds the first WAITING or UPLOADING queue item with matching filename and links task_id."""
    engine = get_engine()
    sql = """
    UPDATE studio_queue_items
    SET task_id = :task_id, status = :status, upload_progress = 100, updated_at = CURRENT_TIMESTAMP
    WHERE id = (
        SELECT id FROM studio_queue_items
        WHERE filename = :filename AND status IN ('WAITING', 'UPLOADING')
        ORDER BY order_index ASC, added_at ASC
        LIMIT 1
    );
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(sql), {"filename": filename, "task_id": task_id, "status": status})
        return True
    except Exception as e:
        logger.warning(f"Error linking task {task_id} by filename {filename}: {e}")
        return False


def requeue_all_completed_studio_tasks(reset_processing: bool = False) -> Dict[str, Any]:
    """
    Resets all completed (and optionally processing/failed) studio tasks back into
    studio_queue_items with status='WAITING', and purges their completed_tasks and transm_tasks records
    so they are re-extracted from scratch with the newly configured LLM/Whisper settings.
    Cross-DB compatible with both SQLite and PostgreSQL.
    """
    engine = get_engine()
    purged_task_ids: set[str] = set()
    requeued_count = 0

    with engine.begin() as conn:
        # 1. Gather all completed studio tasks
        res_comp = conn.execute(text(
            "SELECT task_id, filename FROM completed_tasks WHERE task_type = 'studio' OR task_type IS NULL ORDER BY completed_at ASC;"
        )).fetchall()
        completed_rows = [(str(r[0]), str(r[1])) for r in res_comp if r[0] and r[1]]
        for tid, _ in completed_rows:
            purged_task_ids.add(tid)

        # 2. Gather all studio tasks from transm_tasks
        res_tasks = conn.execute(text(
            "SELECT task_id, filename FROM transm_tasks WHERE LOWER(filename) NOT LIKE '%.srt';"
        )).fetchall()
        for r in res_tasks:
            if r[0]:
                purged_task_ids.add(str(r[0]))

        # 3. Also gather task_ids linked in studio_queue_items
        res_q = conn.execute(text("SELECT task_id FROM studio_queue_items WHERE task_id IS NOT NULL;")).fetchall()
        for r in res_q:
            if r[0]:
                purged_task_ids.add(str(r[0]))

        # 4. Build comprehensive candidate set of (filename -> task_id)
        candidate_map: Dict[str, str] = {}
        for tid, fname in completed_rows:
            if fname and fname not in candidate_map:
                candidate_map[fname] = tid

        for r in res_tasks:
            if r[0] and r[1]:
                fn = str(r[1])
                if fn not in candidate_map:
                    candidate_map[fn] = str(r[0])

        # Also inspect UPLOAD_DIR for uploaded video files
        try:
            from app.config import UPLOAD_DIR
            valid_exts = {'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'ts', 'webm', 'm4v', 'mpg', 'mpeg', 'm2ts', 'mts', 'vob', 'ogv', '3gp'}
            if UPLOAD_DIR.exists():
                for f in UPLOAD_DIR.iterdir():
                    if f.is_file() and f.stat().st_size > 0 and f.suffix.lower().lstrip('.') in valid_exts:
                        clean_fn = f.name
                        if "_" in clean_fn and len(clean_fn.split("_")[0]) in (32, 36):
                            clean_fn = clean_fn.split("_", 1)[1]
                        if clean_fn not in candidate_map:
                            candidate_map[clean_fn] = f"upload_{f.stem[:8]}"
        except Exception:
            pass

        # 5. Ensure all candidate filenames are registered into studio_queue_items
        existing_fnames_res = conn.execute(text("SELECT filename FROM studio_queue_items;")).fetchall()
        existing_fnames = {str(r[0]) for r in existing_fnames_res if r[0]}
        max_order_res = conn.execute(text("SELECT COALESCE(MAX(order_index), -1) FROM studio_queue_items;")).scalar()
        next_order = int(max_order_res if max_order_res is not None else -1) + 1

        for fname, tid in candidate_map.items():
            if fname and fname not in existing_fnames:
                qid = f"studio_requeue_{tid[:8]}"
                conn.execute(text("""
                    INSERT INTO studio_queue_items (id, filename, size, status, upload_progress, task_id, error, order_index, client_id, updated_at)
                    VALUES (:id, :filename, 0, 'WAITING', 0, NULL, NULL, :order_index, 'server', CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET status = 'WAITING', task_id = NULL, error = NULL;
                """), {"id": qid, "filename": fname, "order_index": next_order})
                existing_fnames.add(fname)
                next_order += 1

        # 6. Delete old records from completed_tasks and transm_tasks to prevent stale completion state
        conn.execute(text("DELETE FROM completed_tasks WHERE task_type = 'studio' OR task_type IS NULL;"))
        if purged_task_ids:
            purged_list = list(purged_task_ids)
            placeholders = [f":id_{i}" for i in range(len(purged_list))]
            params = {f"id_{i}": tid for i, tid in enumerate(purged_list)}
            in_clause = ",".join(placeholders)
            conn.execute(text(f"DELETE FROM transm_tasks WHERE task_id IN ({in_clause});"), params)
        conn.execute(text("DELETE FROM transm_tasks WHERE LOWER(filename) NOT LIKE '%.srt';"))

        # 7. Reset ALL studio_queue_items back to WAITING
        conn.execute(text("""
            UPDATE studio_queue_items
            SET status = 'WAITING',
                upload_progress = 0,
                task_id = NULL,
                error = NULL,
                updated_at = CURRENT_TIMESTAMP;
        """))

        # 8. Count total waiting items
        total_waiting = conn.execute(text("SELECT count(*) FROM studio_queue_items WHERE status = 'WAITING';")).scalar()
        requeued_count = int(total_waiting or 0)

    logger.info(f"Re-queued {requeued_count} studio tasks back to WAITING (purged {len(purged_task_ids)} old task records).")
    return {
        "requeued_count": requeued_count,
        "purged_task_ids": list(purged_task_ids)
    }


# ==============================================================================
# Proper Noun Dictionary Database Operations (고유명사 사전)
# ==============================================================================

def get_dictionary_entries(
    page: int = 1,
    size: int = 50,
    query: Optional[str] = None
) -> Dict[str, Any]:
    """Returns paginated proper noun dictionary entries (50 per page by default)."""
    engine = get_engine()
    page = max(1, int(page))
    size = max(1, min(200, int(size)))
    offset = (page - 1) * size

    where_clause = ""
    params: Dict[str, Any] = {"limit": size, "offset": offset}
    if query and query.strip():
        q = f"%{query.strip().lower()}%"
        where_clause = "WHERE LOWER(source_word) LIKE :q OR LOWER(target_word) LIKE :q OR LOWER(COALESCE(notes, '')) LIKE :q"
        params["q"] = q

    count_sql = f"SELECT COUNT(*) FROM proper_noun_dictionary {where_clause};"
    list_sql = f"""
    SELECT id, source_word, target_word, notes, created_at, updated_at
    FROM proper_noun_dictionary
    {where_clause}
    ORDER BY id DESC
    LIMIT :limit OFFSET :offset;
    """

    with engine.connect() as conn:
        total = conn.execute(text(count_sql), params).scalar() or 0
        rows = conn.execute(text(list_sql), params).mappings().all()
        items = []
        for r in rows:
            d = dict(r)
            if d.get("created_at") and hasattr(d["created_at"], "isoformat"):
                d["created_at"] = d["created_at"].isoformat()
            elif d.get("created_at"):
                d["created_at"] = str(d["created_at"])
            if d.get("updated_at") and hasattr(d["updated_at"], "isoformat"):
                d["updated_at"] = d["updated_at"].isoformat()
            elif d.get("updated_at"):
                d["updated_at"] = str(d["updated_at"])
            items.append(d)

    total_pages = max(1, (total + size - 1) // size)
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "total_pages": total_pages
    }


def get_all_dictionary_map() -> Dict[str, str]:
    """Returns entire dictionary as {source_word: target_word} mapping for fast translation lookup."""
    engine = get_engine()
    sql = "SELECT source_word, target_word FROM proper_noun_dictionary ORDER BY LENGTH(source_word) DESC;"
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
            return {str(r[0]): str(r[1]) for r in rows if r[0] and r[1]}
    except Exception as e:
        logger.warning(f"Error fetching all dictionary map: {e}")
        return {}


def add_dictionary_entry(source_word: str, target_word: str, notes: Optional[str] = None) -> Dict[str, Any]:
    """Inserts a new dictionary entry or updates if source_word already exists."""
    engine = get_engine()
    s_word = source_word.strip()
    t_word = target_word.strip()
    if not s_word or not t_word:
        raise ValueError("원문 단어와 번역 단어는 필수입니다.")

    sql = """
    INSERT INTO proper_noun_dictionary (source_word, target_word, notes, updated_at)
    VALUES (:src, :tgt, :notes, CURRENT_TIMESTAMP)
    ON CONFLICT (source_word) DO UPDATE SET
        target_word = EXCLUDED.target_word,
        notes = COALESCE(EXCLUDED.notes, proper_noun_dictionary.notes),
        updated_at = CURRENT_TIMESTAMP;
    """
    with engine.begin() as conn:
        conn.execute(text(sql), {"src": s_word, "tgt": t_word, "notes": notes or ""})

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, source_word, target_word, notes, created_at, updated_at FROM proper_noun_dictionary WHERE source_word = :src"),
            {"src": s_word}
        ).mappings().first()
        res = dict(row)
        if res.get("created_at") and hasattr(res["created_at"], "isoformat"):
            res["created_at"] = res["created_at"].isoformat()
        if res.get("updated_at") and hasattr(res["updated_at"], "isoformat"):
            res["updated_at"] = res["updated_at"].isoformat()
        return res


def update_dictionary_entry(entry_id: int, source_word: str, target_word: str, notes: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Updates an existing dictionary entry by ID."""
    engine = get_engine()
    s_word = source_word.strip()
    t_word = target_word.strip()
    if not s_word or not t_word:
        raise ValueError("원문 단어와 번역 단어는 필수입니다.")

    sql = """
    UPDATE proper_noun_dictionary
    SET source_word = :src, target_word = :tgt, notes = :notes, updated_at = CURRENT_TIMESTAMP
    WHERE id = :id;
    """
    with engine.begin() as conn:
        conn.execute(text(sql), {"id": entry_id, "src": s_word, "tgt": t_word, "notes": notes or ""})

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, source_word, target_word, notes, created_at, updated_at FROM proper_noun_dictionary WHERE id = :id"),
            {"id": entry_id}
        ).mappings().first()
        if not row:
            return None
        res = dict(row)
        if res.get("created_at") and hasattr(res["created_at"], "isoformat"):
            res["created_at"] = res["created_at"].isoformat()
        if res.get("updated_at") and hasattr(res["updated_at"], "isoformat"):
            res["updated_at"] = res["updated_at"].isoformat()
        return res


def delete_dictionary_entry(entry_id: int) -> bool:
    """Deletes a dictionary entry by ID."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM proper_noun_dictionary WHERE id = :id;"), {"id": entry_id})
    return True


def batch_delete_dictionary_entries(ids: List[int]) -> int:
    """Deletes multiple dictionary entries by IDs."""
    if not ids:
        return 0
    clean_ids = [int(i) for i in ids if str(i).isdigit()]
    if not clean_ids:
        return 0
    engine = get_engine()
    placeholders = [f":id_{i}" for i in range(len(clean_ids))]
    params = {f"id_{i}": cid for i, cid in enumerate(clean_ids)}
    in_clause = ",".join(placeholders)
    sql = f"DELETE FROM proper_noun_dictionary WHERE id IN ({in_clause});"
    with engine.begin() as conn:
        res = conn.execute(text(sql), params)
        return res.rowcount

