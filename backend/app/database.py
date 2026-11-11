import json
import logging
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from app.config import (
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_DB,
    POSTGRES_USER,
    POSTGRES_PASSWORD,
)

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_connected_db_name: Optional[str] = None

def get_engine() -> Engine:
    """Initializes and returns a pooled SQLAlchemy Engine with fallback support."""
    global _engine, _connected_db_name
    if _engine is not None:
        return _engine

    encoded_pw = quote_plus(POSTGRES_PASSWORD)
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

    raise RuntimeError(f"Failed to connect to any PostgreSQL database ({db_candidates}): {last_error}")

def init_db():
    """Initializes schema and tables in PostgreSQL."""
    engine = get_engine()
    create_table_sql = """
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
        raw_segments JSONB,
        checkpoint_segments JSONB,
        subtitles JSONB,
        error TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_transm_tasks_created_at ON transm_tasks (created_at DESC);

    CREATE TABLE IF NOT EXISTS completed_tasks (
        task_id VARCHAR(64) PRIMARY KEY,
        filename VARCHAR(255) NOT NULL,
        subtitle_count INTEGER NOT NULL DEFAULT 0,
        srt_path TEXT,
        srt_download_url TEXT,
        task_type VARCHAR(32) NOT NULL DEFAULT 'studio',
        completed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_completed_tasks_at ON completed_tasks (completed_at DESC);

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
        added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_studio_queue_order ON studio_queue_items (order_index ASC, added_at ASC);
    """
    with engine.begin() as conn:
        conn.execute(text(create_table_sql))

    # Add task_type and download_count columns if table already existed without them
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE completed_tasks ADD COLUMN IF NOT EXISTS task_type VARCHAR(32) DEFAULT 'studio';"))
        conn.execute(text("ALTER TABLE completed_tasks ADD COLUMN IF NOT EXISTS download_count INTEGER DEFAULT 0;"))
        conn.execute(text("ALTER TABLE completed_tasks ADD COLUMN IF NOT EXISTS last_downloaded_at TIMESTAMP WITH TIME ZONE;"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_completed_tasks_type ON completed_tasks (task_type);"))
        conn.execute(text("""
        -- Video files are always studio tasks
        UPDATE completed_tasks
        SET task_type = 'studio'
        WHERE filename ILIKE '%.mp4' 
           OR filename ILIKE '%.mkv' 
           OR filename ILIKE '%.avi' 
           OR filename ILIKE '%.mov' 
           OR filename ILIKE '%.wmv' 
           OR filename ILIKE '%.flv' 
           OR filename ILIKE '%.ts' 
           OR filename ILIKE '%.webm';

        -- Pure SRT files are translator tasks
        UPDATE completed_tasks
        SET task_type = 'translator'
        WHERE filename ILIKE '%.srt' AND (task_type IS NULL OR task_type = 'studio');

        -- Synchronize any completed tasks (including 0-subtitle tasks) from transm_tasks that are not yet in completed_tasks
        INSERT INTO completed_tasks (
            task_id, filename, subtitle_count, srt_path, srt_download_url, task_type, completed_at, download_count
        )
        SELECT 
            t.task_id,
            t.filename,
            COALESCE(jsonb_array_length(CASE WHEN jsonb_typeof(t.subtitles) = 'array' THEN t.subtitles ELSE '[]'::jsonb END), 0) AS subtitle_count,
            t.srt_path,
            t.srt_download_url,
            CASE WHEN t.filename ILIKE '%.srt' THEN 'translator' ELSE 'studio' END AS task_type,
            COALESCE(t.updated_at, CURRENT_TIMESTAMP) AS completed_at,
            0 AS download_count
        FROM transm_tasks t
        WHERE t.status = 'COMPLETED'
          AND NOT EXISTS (
              SELECT 1 FROM completed_tasks c WHERE c.task_id = t.task_id
          );
        """))

    logger.info("Database initialized successfully: transm_tasks and completed_tasks tables are ready.")

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
    """Retrieves full task record from PostgreSQL."""
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
            return json.loads(row)
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
        raw_dict = json.loads(row) if isinstance(row, str) else row
        return {int(k): v for k, v in raw_dict.items()}

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
    """Records or updates a completed subtitle generation task in PostgreSQL."""
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
    sql = """
    UPDATE completed_tasks
    SET download_count = COALESCE(download_count, 0) + 1,
        last_downloaded_at = CURRENT_TIMESTAMP
    WHERE task_id = :task_id
    RETURNING download_count;
    """
    try:
        with engine.begin() as conn:
            res = conn.execute(text(sql), {"task_id": task_id}).scalar()
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
                row_dict["completed_at"] = row_dict["completed_at"].isoformat()
            if row_dict.get("last_downloaded_at"):
                row_dict["last_downloaded_at"] = row_dict["last_downloaded_at"].isoformat()
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
    logger.info(f"Deleted task {task_id} from PostgreSQL database.")
    return True

def delete_tasks_batch(task_ids: List[str]) -> List[str]:
    """Deletes a list of task IDs from both completed_tasks and transm_tasks."""
    if not task_ids:
        return []
    clean_ids = [str(tid) for tid in task_ids if tid]
    if not clean_ids:
        return []
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM completed_tasks WHERE task_id = ANY(:ids);"), {"ids": clean_ids})
        conn.execute(text("DELETE FROM transm_tasks WHERE task_id = ANY(:ids);"), {"ids": clean_ids})
    logger.info(f"Deleted {len(clean_ids)} tasks from PostgreSQL database in batch.")
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
                conn.execute(text("DELETE FROM completed_tasks WHERE task_type = :tt;"), {"tt": task_type})
                conn.execute(text("DELETE FROM transm_tasks WHERE task_id = ANY(:ids);"), {"ids": ids})
            logger.info(f"Deleted all {len(ids)} {task_type} tasks from PostgreSQL database.")
            return ids
        else:
            res = conn.execute(text("SELECT task_id FROM completed_tasks;"))
            ids = [str(r[0]) for r in res.fetchall()]
            conn.execute(text("DELETE FROM completed_tasks;"))
            conn.execute(text("DELETE FROM transm_tasks;"))
            logger.info(f"Deleted all {len(ids)} tasks from PostgreSQL database.")
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
                    row_dict["added_at"] = row_dict["added_at"].isoformat()
                if row_dict.get("updated_at"):
                    row_dict["updated_at"] = row_dict["updated_at"].isoformat()
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
                    # Completed items should be removed from studio_queue_items (only if not reset to WAITING)
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
    """
    engine = get_engine()
    purged_task_ids: set[str] = set()
    requeued_count = 0

    with engine.begin() as conn:
        # 1. Gather all completed studio tasks
        res_comp = conn.execute(text(
            "SELECT task_id, filename FROM completed_tasks WHERE task_type = 'studio' OR task_type IS NULL ORDER BY completed_at ASC;"
        )).fetchall()
        completed_rows = [(str(r[0]), str(r[1])) for r in res_comp if r[0]]
        for tid, _ in completed_rows:
            purged_task_ids.add(tid)

        # 2. Gather studio tasks in transm_tasks
        if reset_processing:
            res_tasks = conn.execute(text(
                "SELECT task_id, filename FROM transm_tasks WHERE filename NOT ILIKE '%.srt';"
            )).fetchall()
        else:
            res_tasks = conn.execute(text(
                "SELECT task_id, filename FROM transm_tasks WHERE status IN ('COMPLETED', 'FAILED') AND filename NOT ILIKE '%.srt';"
            )).fetchall()
        for r in res_tasks:
            if r[0]:
                purged_task_ids.add(str(r[0]))

        # 3. Also gather task_ids linked in studio_queue_items
        if reset_processing:
            res_q = conn.execute(text("SELECT task_id FROM studio_queue_items WHERE task_id IS NOT NULL;")).fetchall()
        else:
            res_q = conn.execute(text("SELECT task_id FROM studio_queue_items WHERE status IN ('COMPLETED', 'FAILED') AND task_id IS NOT NULL;")).fetchall()
        for r in res_q:
            if r[0]:
                purged_task_ids.add(str(r[0]))

        # 4. Ensure any completed studio task whose filename is missing from studio_queue_items is inserted
        existing_fnames_res = conn.execute(text("SELECT filename FROM studio_queue_items;")).fetchall()
        existing_fnames = {str(r[0]) for r in existing_fnames_res if r[0]}
        max_order_res = conn.execute(text("SELECT COALESCE(MAX(order_index), -1) FROM studio_queue_items;")).scalar()
        next_order = int(max_order_res if max_order_res is not None else -1) + 1

        for tid, fname in completed_rows:
            if fname and fname not in existing_fnames:
                qid = f"studio_requeue_{tid[:8]}"
                conn.execute(text("""
                    INSERT INTO studio_queue_items (id, filename, size, status, upload_progress, task_id, error, order_index, client_id, updated_at)
                    VALUES (:id, :filename, 0, 'WAITING', 0, NULL, NULL, :order_index, 'server', CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO NOTHING;
                """), {"id": qid, "filename": fname, "order_index": next_order})
                existing_fnames.add(fname)
                next_order += 1

        # 5. Delete completed studio tasks from completed_tasks and transm_tasks
        conn.execute(text("DELETE FROM completed_tasks WHERE task_type = 'studio' OR task_type IS NULL;"))
        if purged_task_ids:
            conn.execute(text("DELETE FROM transm_tasks WHERE task_id = ANY(:ids);"), {"ids": list(purged_task_ids)})
        if not reset_processing:
            conn.execute(text("DELETE FROM transm_tasks WHERE status IN ('COMPLETED', 'FAILED') AND filename NOT ILIKE '%.srt';"))
        else:
            conn.execute(text("DELETE FROM transm_tasks WHERE filename NOT ILIKE '%.srt';"))

        # 6. Reset studio_queue_items back to WAITING
        if reset_processing:
            upd = conn.execute(text("""
                UPDATE studio_queue_items
                SET status = 'WAITING',
                    upload_progress = 0,
                    task_id = NULL,
                    error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status != 'WAITING' OR task_id IS NOT NULL;
            """))
            requeued_count = upd.rowcount
        else:
            upd = conn.execute(text("""
                UPDATE studio_queue_items
                SET status = 'WAITING',
                    upload_progress = 0,
                    task_id = NULL,
                    error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('COMPLETED', 'FAILED');
            """))
            requeued_count = upd.rowcount

    logger.info(f"Re-queued {requeued_count} studio tasks back to WAITING (purged {len(purged_task_ids)} old task records).")
    return {
        "requeued_count": requeued_count,
        "purged_task_ids": list(purged_task_ids)
    }




