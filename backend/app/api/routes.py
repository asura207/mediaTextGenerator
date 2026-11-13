import os
import time
import json
import uuid
import logging
import urllib.parse
import io
import re
import zipfile
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from pydantic import BaseModel
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException, status, Request, Query
from fastapi.responses import FileResponse, StreamingResponse, Response
from starlette.concurrency import run_in_threadpool
import aiofiles
import pysrt
import ollama

from app.config import (
    UPLOAD_DIR,
    PROCESSED_DIR,
    OLLAMA_HOST,
    get_runtime_settings,
    update_runtime_settings,
    get_ollama_model,
    get_active_llm_config,
    get_active_llm_provider,
    get_whisper_config,
    get_media_scan_dirs
)
from app.models import (
    TaskStatus,
    SubtitleSegment,
    UpdateSubtitlesRequest,
    DictionaryEntryCreate,
    DictionaryEntryUpdate,
    DictionaryBatchDelete,
    CloudLLMTestRequest,
)
from app.services.audio_extractor import extract_audio
from app.services.whisper_stt import transcribe_audio
from app.services.llm_refiner import refine_subtitles_with_llm
from app.services.srt_generator import generate_srt_file, optimize_subtitle_timing
from app.services.language_detector import detect_subtitles_language, detect_text_language
from app.services.subtitle_translator import translate_subtitles_list, TARGET_LANG_NAMES
import app.database as db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["subtitles"])

# In-memory Task Repository (persisted in PostgreSQL with local disk fallback)
tasks: Dict[str, TaskStatus] = {}
task_video_paths: Dict[str, Path] = {}
task_srt_paths: Dict[str, Path] = {}

def save_task_state(task_id: str):
    """Persists task state to PostgreSQL database and local disk fallback."""
    if task_id not in tasks:
        return
    task = tasks[task_id]

    video_p = str(task_video_paths.get(task_id)) if task_id in task_video_paths else None
    audio_f = PROCESSED_DIR / f"{task_id}.wav"
    audio_p = str(audio_f) if audio_f.exists() else None
    srt_p = str(task_srt_paths.get(task_id)) if task_id in task_srt_paths else None

    # 1. PostgreSQL Persistence
    try:
        db.upsert_task(
            task_id=task_id,
            filename=task.filename,
            status=task.status,
            stage=task.stage,
            progress=task.progress,
            video_path=video_p,
            audio_path=audio_p,
            srt_path=srt_p,
            srt_download_url=task.srt_download_url,
            error=task.error,
        )
    except Exception as db_err:
        logger.warning(f"Failed to persist task state to PostgreSQL for {task_id}: {db_err}")

    # 2. Local disk fallback
    try:
        state_file = PROCESSED_DIR / f"{task_id}_state.json"
        with open(state_file, "w", encoding="utf-8") as f:
            f.write(task.model_dump_json(indent=2))
    except Exception as disk_err:
        logger.warning(f"Failed to save local state file for {task_id}: {disk_err}")

def generate_web_preview(video_path: Path, preview_path: Path) -> bool:
    """Generates a fast, lightweight H.264/AAC MP4 preview for web browser playback."""
    temp_preview = preview_path.with_suffix(".tmp.mp4")
    try:
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vf", "scale=-2:480",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(temp_preview),
            "-y"
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        if temp_preview.exists() and temp_preview.stat().st_size > 0:
            if preview_path.exists():
                preview_path.unlink()
            temp_preview.rename(preview_path)
            logger.info(f"Web preview MP4 generated: {preview_path.name}")
            return True
        return False
    except Exception as e:
        logger.warning(f"Web preview conversion failed for {video_path.name}: {e}")
        return False
    finally:
        if temp_preview.exists():
            try:
                temp_preview.unlink()
            except Exception:
                pass


_LOCAL_MEDIA_INDEX: Dict[str, Path] = {}
_LOCAL_MEDIA_ALL_PATHS: List[Any] = []
_LOCAL_MEDIA_INDEX_TS: float = 0.0
_auto_start_lock = threading.Lock()
_preview_gen_in_progress: set[str] = set()
_preview_gen_lock = threading.Lock()

_SRT_FALLBACK_ENCODINGS = (
    "utf-8-sig",
    "utf-8",
    "utf-16",
    "cp949",
    "euc-kr",
    "gb18030",
    "big5",
    "shift_jis",
    "cp1251",
    "cp1256",
    "cp874",
    "cp1254",
    "cp1252",
    "latin-1",
)


def parse_srt_bytes_multi_encoding(raw_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Decodes raw .srt bytes across UTF-8, UTF-16, and regional encodings worldwide,
    returning normalized subtitle segment dicts.
    """
    content_str: Optional[str] = None
    for enc in _SRT_FALLBACK_ENCODINGS:
        try:
            decoded = raw_bytes.decode(enc)
            if "-->" not in decoded:
                continue
            content_str = decoded
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if content_str is None:
        content_str = raw_bytes.decode("utf-8", errors="replace")

    subs_pysrt = pysrt.from_string(content_str)
    segments: List[Dict[str, Any]] = []
    for idx, sub in enumerate(subs_pysrt, start=1):
        start_sec = sub.start.ordinal / 1000.0
        end_sec = sub.end.ordinal / 1000.0
        start_str = str(sub.start).replace(".", ",")
        end_str = str(sub.end).replace(".", ",")
        segments.append({
            "index": sub.index or idx,
            "start": start_sec,
            "end": end_sec,
            "start_str": start_str,
            "end_str": end_str,
            "start_time_str": start_str,
            "end_time_str": end_str,
            "text": sub.text,
            "raw_text": sub.text,
            "refined_text": sub.text,
        })
    return segments


def parse_srt_segments_multi_encoding(srt_file: Any) -> List[Dict[str, Any]]:
    """Parses an .srt file from disk supporting UTF-8, UTF-16, CJK, Cyrillic, Arabic, European encodings."""
    return parse_srt_bytes_multi_encoding(Path(srt_file).read_bytes())


def schedule_web_preview(task_id: str, video_path: Path, preview_path: Path) -> None:
    """Starts non-blocking background web-preview generation once per task_id."""
    with _preview_gen_lock:
        if task_id in _preview_gen_in_progress or preview_path.exists():
            return
        _preview_gen_in_progress.add(task_id)

    def _worker():
        try:
            generate_web_preview(video_path, preview_path)
        finally:
            with _preview_gen_lock:
                _preview_gen_in_progress.discard(task_id)

    threading.Thread(target=_worker, daemon=True).start()

VALID_VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv",
    ".asf", ".ts", ".m4v", ".mpg", ".mpeg", ".m2ts", ".mts", ".vob", ".ogv", ".3gp"
}


def find_video_file_on_server(filename: str) -> Optional[Path]:
    """
    Locates video file on the server.
    Supports absolute paths, subfolder relative paths (e.g. 'SubFolder/01.mkv'), and base filenames.
    Checks UPLOAD_DIR first, then checks known local source media directories using an os.walk index
    (safe against special glob characters like '[' and ']').
    """
    global _LOCAL_MEDIA_INDEX, _LOCAL_MEDIA_ALL_PATHS, _LOCAL_MEDIA_INDEX_TS
    if not filename:
        return None

    # 0. Check if filename is already a valid absolute or direct path on disk
    try:
        direct_candidate = Path(filename)
        if direct_candidate.is_absolute() and direct_candidate.exists() and direct_candidate.is_file() and direct_candidate.stat().st_size > 0:
            return direct_candidate
    except Exception:
        pass

    base_name = Path(filename.replace("\\", "/")).name

    # 1. Check UPLOAD_DIR safely via iterdir (handles '[' and ']' in filenames)
    try:
        for f in UPLOAD_DIR.iterdir():
            if f.is_file() and f.stat().st_size > 0 and (f.name == base_name or f.name.endswith(f"_{base_name}")):
                return f
    except Exception:
        pass

    # 2. Check cached local media index (by exact filename / relative path)
    cached = _LOCAL_MEDIA_INDEX.get(filename)
    if cached and cached.exists() and cached.is_file() and cached.stat().st_size > 0:
        return cached

    # 3. Refresh local media index if needed (throttled to once every 10s)
    now = time.time()
    if now - _LOCAL_MEDIA_INDEX_TS > 10.0 or not _LOCAL_MEDIA_INDEX:
        _LOCAL_MEDIA_INDEX_TS = now
        search_roots = get_media_scan_dirs()
        new_index: Dict[str, Path] = dict(_LOCAL_MEDIA_INDEX)
        all_paths: List[Any] = list(_LOCAL_MEDIA_ALL_PATHS)
        seen_full = {p_str for p_str, _ in all_paths}
        for root in search_roots:
            try:
                if root.exists():
                    for dirpath, _, filenames in os.walk(str(root)):
                        for fn in filenames:
                            full_p = Path(dirpath) / fn
                            norm_full = str(full_p).replace("\\", "/").lower()
                            if norm_full not in seen_full:
                                seen_full.add(norm_full)
                                all_paths.append((norm_full, full_p))
                            if fn not in new_index:
                                new_index[fn] = full_p
            except Exception:
                pass
        _LOCAL_MEDIA_INDEX = new_index
        _LOCAL_MEDIA_ALL_PATHS = all_paths

    # 4. If filename includes subfolder path (e.g. '사이버포뮬라/DOUBLE/01.mkv' or 'DOUBLE/01.mkv'), match suffix first!
    norm_query = filename.replace("\\", "/").lstrip("/").lower()
    if "/" in norm_query:
        suffix = "/" + norm_query
        for norm_full, full_p in _LOCAL_MEDIA_ALL_PATHS:
            if norm_full.endswith(suffix) and full_p.exists() and full_p.is_file() and full_p.stat().st_size > 0:
                _LOCAL_MEDIA_INDEX[filename] = full_p
                return full_p

    cached = _LOCAL_MEDIA_INDEX.get(filename) or _LOCAL_MEDIA_INDEX.get(base_name)
    if cached and cached.exists() and cached.is_file() and cached.stat().st_size > 0:
        return cached

    # Fallback: partial stem match in _LOCAL_MEDIA_INDEX
    stem = Path(base_name).stem
    if stem:
        for fn, fpath in _LOCAL_MEDIA_INDEX.items():
            if stem in fn and fpath.exists() and fpath.is_file() and fpath.stat().st_size > 0:
                return fpath

    return None


def auto_start_next_waiting_item(background_tasks: Optional[BackgroundTasks] = None) -> Optional[Dict[str, Any]]:
    """
    Finds the next WAITING item in studio_queue_items.
    If its video file exists on the server, automatically starts the pipeline!
    """
    with _auto_start_lock:
        # 1. Check if another studio task is already running
        for tid, t in tasks.items():
            if t.status in ("PROCESSING", "PENDING"):
                if not ("번역" in (t.stage or "") or (t.filename and t.filename.endswith(".srt"))):
                    return {"started": False, "message": "이미 진행 중인 작업이 있습니다.", "task_id": tid}

        # 2. Get waiting items from DB
        db_items = db.get_studio_queue()
        completed_tasks = []
        try:
            completed_tasks = db.get_completed_tasks(limit=50000)
        except Exception:
            pass
        completed_task_ids = {ct.get("task_id") for ct in completed_tasks if ct.get("task_id")}

        waiting_items = [it for it in db_items if it.get("status") == "WAITING"]
        if not waiting_items:
            return {"started": False, "message": "대기 중인 작업이 없습니다."}

        for next_item in waiting_items:
            fname = next_item.get("filename")
            qid = next_item.get("id")
            tid = next_item.get("task_id")
            if not fname:
                continue

            # Only remove if this specific queue item's task_id is already completed
            if tid and tid in completed_task_ids:
                try:
                    db.delete_studio_queue_item(qid)
                except Exception:
                    pass
                continue

            video_path = find_video_file_on_server(fname)
            if video_path and video_path.exists() and video_path.stat().st_size > 0:
                new_task_id = str(uuid.uuid4())
                display_filename = fname.replace("\\", "/").lstrip("/")

                task_video_paths[new_task_id] = video_path
                tasks[new_task_id] = TaskStatus(
                    task_id=new_task_id,
                    status="PROCESSING",
                    stage="동영상 대기열 순차 처리 시작...",
                    progress=10,
                    filename=display_filename,
                    video_url=f"/api/video/{new_task_id}"
                )

                # Link queue item in DB
                db.update_queue_item_task_link(qid, new_task_id, "PROCESSING")

                # Launch pipeline
                if background_tasks:
                    background_tasks.add_task(run_pipeline, new_task_id, video_path, display_filename)
                else:
                    threading.Thread(target=run_pipeline, args=(new_task_id, video_path, display_filename), daemon=True).start()

                logger.info(f"Auto-started queue item {qid} ({display_filename}) -> task {new_task_id} from {video_path}")
                return {
                    "started": True,
                    "queue_id": qid,
                    "task_id": new_task_id,
                    "filename": display_filename,
                    "message": f"'{display_filename}' 작업이 자동으로 시작되었습니다."
                }

        return {"started": False, "message": "서버에 대기 중인 영상 파일을 찾을 수 없어 클라이언트 업로드를 기다립니다."}


def run_pipeline(task_id: str, video_path: Path, filename: str):
    """Asynchronous background worker executing the full subtitle pipeline with DB persistence."""
    try:
        # Step 1: Audio Extraction (Skip if already extracted)
        audio_path = PROCESSED_DIR / f"{task_id}.wav"
        if audio_path.exists() and audio_path.stat().st_size > 0:
            logger.info(f"Reusing existing extracted audio: {audio_path}")
            tasks[task_id].stage = "기존 오디오 파일 재사용..."
            tasks[task_id].progress = 25
            save_task_state(task_id)
        else:
            tasks[task_id].stage = "오디오 추출 중 (moviepy)..."
            tasks[task_id].progress = 25
            save_task_state(task_id)
            extract_audio(video_path, audio_path)

        # For formats unsupported natively in web browsers (WMV, ASF, AVI, etc.), generate preview MP4 in background thread
        if video_path.suffix.lower() in ['.wmv', '.asf', '.avi']:
            preview_file = PROCESSED_DIR / f"{task_id}_preview.mp4"
            if not preview_file.exists():
                threading.Thread(
                    target=generate_web_preview,
                    args=(video_path, preview_file),
                    daemon=True
                ).start()

        # Step 2: Speech to Text (faster-whisper) (Check PostgreSQL / cache first)
        raw_segments = None
        try:
            raw_segments = db.get_raw_segments(task_id)
            if raw_segments:
                logger.info(f"Loaded {len(raw_segments)} raw segments from PostgreSQL DB for task {task_id}")
        except Exception as e:
            logger.warning(f"Could not load raw segments from DB: {e}")

        raw_segments_path = PROCESSED_DIR / f"{task_id}_raw.json"
        if not raw_segments and raw_segments_path.exists() and raw_segments_path.stat().st_size > 0:
            logger.info(f"Loading raw segments from disk cache: {raw_segments_path}")
            with open(raw_segments_path, "r", encoding="utf-8") as f:
                raw_segments = json.load(f)

        if raw_segments:
            tasks[task_id].stage = "기존 STT 결과 불러오는 중..."
            tasks[task_id].progress = 50
            save_task_state(task_id)
        else:
            w_model = get_whisper_config().get("model_size", "large-v3-turbo")
            tasks[task_id].stage = f"음성 인식 및 타임스탬프 추출 준비 중 (Whisper {w_model})..."
            tasks[task_id].progress = 26
            save_task_state(task_id)

            def on_whisper_progress(curr_sec: float, total_sec: float):
                # Scale faster-whisper STT between 26% and 50%
                pct = 26 + int((curr_sec / max(total_sec, 1.0)) * 24)
                tasks[task_id].progress = min(pct, 50)
                cur_m, cur_s = int(curr_sec // 60), int(curr_sec % 60)
                tot_m, tot_s = int(total_sec // 60), int(total_sec % 60)
                tasks[task_id].stage = f"Whisper ({w_model}) 음성 인식 중... ({cur_m:02d}:{cur_s:02d} / {tot_m:02d}:{tot_s:02d})"
                save_task_state(task_id)

            raw_segments = transcribe_audio(audio_path, progress_callback=on_whisper_progress)
            
            # Persist to PostgreSQL and disk
            try:
                db.save_raw_segments(task_id, raw_segments)
            except Exception as e:
                logger.warning(f"Could not save raw segments to PostgreSQL: {e}")
            with open(raw_segments_path, "w", encoding="utf-8") as f:
                json.dump(raw_segments, f, ensure_ascii=False, indent=2)

        if not raw_segments:
            logger.info(f"No speech detected for task {task_id}.")
            tasks[task_id].subtitles = []
            srt_path = PROCESSED_DIR / f"{task_id}.srt"
            generate_srt_file([], srt_path)
            task_srt_paths[task_id] = srt_path

            try:
                db.save_subtitles(task_id, [])
                db.add_completed_task(
                    task_id=task_id,
                    filename=filename,
                    subtitle_count=0,
                    srt_path=str(srt_path),
                    srt_download_url=f"/api/download/{task_id}",
                    task_type="studio"
                )
            except Exception as e:
                logger.warning(f"Failed to record 0-subtitle completed task to DB: {e}")

            tasks[task_id].status = "COMPLETED"
            tasks[task_id].stage = "음성이 감지되지 않았습니다 (자막 0건)"
            tasks[task_id].progress = 100
            save_task_state(task_id)
            db.delete_studio_queue_by_task_id(task_id, filename=filename)
            try:
                auto_start_next_waiting_item()
            except Exception as e_next:
                logger.warning(f"Error auto-starting next queue item after 0-sub task: {e_next}")
            return

        # Step 3: LLM Context Refinement (with PostgreSQL batch checkpointing)
        active_cfg = get_active_llm_config()
        active_prov = active_cfg.get("provider", "ollama")
        active_model_name = active_cfg.get("model", "gemma4:12b")
        tasks[task_id].stage = f"{active_prov.upper()} ({active_model_name}) 모델로 문맥 교정 준비 중..."
        tasks[task_id].progress = 55
        save_task_state(task_id)

        checkpoint_path = PROCESSED_DIR / f"{task_id}_checkpoint.json"
        
        # Load initial checkpoint from PostgreSQL
        initial_checkpoint = None
        try:
            initial_checkpoint = db.get_checkpoint_segments(task_id)
        except Exception as e:
            logger.warning(f"Could not load checkpoint from DB: {e}")

        def on_checkpoint_save(cp_map: Dict[int, str]):
            try:
                db.save_checkpoint_segments(task_id, cp_map)
            except Exception as e:
                logger.warning(f"Failed to save checkpoint to PostgreSQL: {e}")

        def on_refine_progress(current_batch: int, total_batches: int):
            percent = 55 + int((current_batch / total_batches) * 35)
            tasks[task_id].progress = min(percent, 89)
            cfg = get_active_llm_config()
            cur_prov = cfg.get("provider", "ollama")
            cur_llm = cfg.get("model", "gemma4:12b")
            tasks[task_id].stage = f"{cur_prov.upper()} ({cur_llm}) 자막 교정 중... ({current_batch}/{total_batches} 완료)"
            save_task_state(task_id)

        refined_segments = refine_subtitles_with_llm(
            raw_segments,
            progress_callback=on_refine_progress,
            checkpoint_callback=on_checkpoint_save,
            initial_checkpoint=initial_checkpoint,
            checkpoint_path=checkpoint_path
        )

        # Optimize subtitle timing so subtitles disappear when dialogue ends
        refined_segments = optimize_subtitle_timing(refined_segments)

        # Step 4: SRT Subtitle Generation
        tasks[task_id].stage = "SRT 자막 파일 생성 중..."
        tasks[task_id].progress = 90
        save_task_state(task_id)
        srt_path = PROCESSED_DIR / f"{task_id}.srt"
        generate_srt_file(refined_segments, srt_path)
        task_srt_paths[task_id] = srt_path

        # Step 5: Completion & Subtitle Persistence
        sub_models = [SubtitleSegment(**seg) for seg in refined_segments]
        sub_dicts = [seg if isinstance(seg, dict) else seg.model_dump() for seg in refined_segments]
        try:
            db.save_subtitles(task_id, sub_dicts)
            db.add_completed_task(
                task_id=task_id,
                filename=filename,
                subtitle_count=len(sub_models),
                srt_path=str(srt_path),
                srt_download_url=f"/api/download/{task_id}",
                task_type="studio"
            )
        except Exception as e:
            logger.warning(f"Failed to save subtitles/completed task to DB: {e}")

        tasks[task_id].subtitles = sub_models
        tasks[task_id].srt_download_url = f"/api/download/{task_id}"
        tasks[task_id].status = "COMPLETED"
        tasks[task_id].stage = "자막 생성 및 교정 완료"
        tasks[task_id].progress = 100
        save_task_state(task_id)
        db.delete_studio_queue_by_task_id(task_id, filename=filename)
        logger.info(f"Task {task_id} completed successfully, saved to PostgreSQL, and removed from studio queue.")

        # Clean up temporary audio file to preserve disk space
        try:
            if audio_path.exists():
                audio_path.unlink(missing_ok=True)
                logger.info(f"Temporary audio file cleaned up: {audio_path}")
        except Exception as e_clean:
            logger.warning(f"Could not clean up temporary audio {audio_path}: {e_clean}")

        # Check and auto-start next queued item immediately
        try:
            auto_start_next_waiting_item()
        except Exception as e_next:
            logger.warning(f"Error auto-starting next queue item: {e_next}")

    except Exception as e:
        logger.exception(f"Pipeline error for task {task_id}: {e}")
        tasks[task_id].status = "FAILED"
        tasks[task_id].stage = "처리 중 오류 발생"
        tasks[task_id].error = str(e)
        save_task_state(task_id)
        db.update_queue_status_by_task_id(task_id, "FAILED", error=str(e), filename=filename)
        try:
            auto_start_next_waiting_item()
        except Exception as e_next:
            logger.warning(f"Error auto-starting next queue item on failure: {e_next}")


@router.post("/upload", response_model=Dict[str, str], status_code=status.HTTP_202_ACCEPTED)
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    queue_id: Optional[str] = Form(None),
    relative_path: Optional[str] = Form(None)
):
    """
    Accepts video upload, saves file asynchronously in chunks,
    and launches the transcription/refinement pipeline in the background.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")

    task_id = str(uuid.uuid4())
    sanitized_filename = Path(file.filename.replace("\\", "/")).name
    display_filename = (relative_path or file.filename).replace("\\", "/").lstrip("/")
    video_path = UPLOAD_DIR / f"{task_id}_{sanitized_filename}"

    # Asynchronously stream large files to disk
    try:
        async with aiofiles.open(video_path, "wb") as out_file:
            while chunk := await file.read(1024 * 1024 * 4): # 4MB chunk
                await out_file.write(chunk)
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        raise HTTPException(status_code=500, detail="File upload failed on server.")

    # Register task initial state
    task_video_paths[task_id] = video_path
    tasks[task_id] = TaskStatus(
        task_id=task_id,
        status="PROCESSING",
        stage="동영상 업로드 완료. 파이프라인 시작 대기 중...",
        progress=10,
        filename=display_filename,
        video_url=f"/api/video/{task_id}"
    )

    # Immediately link in studio_queue_items if this video was queued
    try:
        if queue_id:
            db.update_queue_item_task_link(queue_id, task_id, status="PROCESSING")
        else:
            db.link_queue_item_by_filename(display_filename, task_id, status="PROCESSING")
    except Exception as link_err:
        logger.warning(f"Failed to link queue item for {display_filename}: {link_err}")

    # Trigger background pipeline
    background_tasks.add_task(run_pipeline, task_id, video_path, display_filename)

    return {
        "task_id": task_id,
        "message": "비디오 업로드가 완료되어 자막 생성 파이프라인이 시작되었습니다."
    }


@router.get("/tasks", response_model=List[Dict[str, Any]])
async def list_all_tasks():
    """Returns list of recent tasks stored in PostgreSQL."""
    try:
        return db.get_all_tasks()
    except Exception as e:
        logger.warning(f"Could not fetch tasks from DB: {e}")
        return []


@router.get("/completed-tasks", response_model=List[Dict[str, Any]])
async def list_completed_tasks(
    task_type: Optional[str] = None,
    page: Optional[int] = None,
    page_size: int = 100,
    limit: int = 10000,
    offset: int = 0
):
    """Returns list of completed tasks from PostgreSQL, optionally filtered by task_type and paginated."""
    try:
        if page is not None and page >= 1:
            actual_limit = max(1, page_size)
            actual_offset = (page - 1) * actual_limit
        else:
            actual_limit = max(1, limit)
            actual_offset = max(0, offset)
        return db.get_completed_tasks(limit=actual_limit, task_type=task_type, offset=actual_offset)
    except Exception as e:
        logger.warning(f"Could not fetch completed tasks from DB: {e}")
        return []


@router.post("/completed-tasks/sync-disk")
async def sync_completed_tasks_from_disk_endpoint():
    """
    Scans media root directories and processed directory to discover existing .srt files,
    and restores any unregistered completed tasks into completed_tasks and transm_tasks.
    """
    return await run_in_threadpool(db.sync_disk_srt_to_completed_tasks)


def _restore_task_status_sync(task_id: str) -> Optional[TaskStatus]:
    """Synchronously restores a TaskStatus from DB (transm_tasks / completed_tasks) or disk state."""
    try:
        db_task = db.get_task(task_id)
        if not db_task:
            from sqlalchemy import text
            with db.get_engine().connect() as conn:
                comp = conn.execute(
                    text("SELECT task_id, filename, srt_path, srt_download_url FROM completed_tasks WHERE task_id = :tid"),
                    {"tid": task_id},
                ).mappings().first()
                if comp:
                    db_task = {
                        "task_id": comp["task_id"],
                        "filename": comp["filename"],
                        "status": "COMPLETED",
                        "stage": "작업 완료",
                        "progress": 100,
                        "srt_path": comp.get("srt_path"),
                        "srt_download_url": comp.get("srt_download_url"),
                        "video_path": None,
                        "error": None,
                        "subtitles": None,
                    }

        if db_task:
            subs = []
            if db_task.get("subtitles"):
                subs_raw = db_task["subtitles"]
                if isinstance(subs_raw, str):
                    subs_raw = json.loads(subs_raw)
                subs = [SubtitleSegment(**s) for s in subs_raw]

            srt_file = None
            if db_task.get("srt_path") and Path(db_task["srt_path"]).exists():
                srt_file = Path(db_task["srt_path"])
            elif (PROCESSED_DIR / f"{task_id}.srt").exists():
                srt_file = PROCESSED_DIR / f"{task_id}.srt"

            if srt_file:
                task_srt_paths[task_id] = srt_file
                if not subs:
                    try:
                        parsed_segs = parse_srt_segments_multi_encoding(srt_file)
                        subs = [SubtitleSegment(**s) for s in parsed_segs]
                    except Exception as parse_err:
                        logger.warning(f"Could not parse srt file {srt_file} for task {task_id}: {parse_err}")

            if db_task.get("video_path") and Path(db_task["video_path"]).exists():
                task_video_paths[task_id] = Path(db_task["video_path"])

            task = TaskStatus(
                task_id=db_task["task_id"],
                filename=db_task["filename"],
                status=db_task["status"],
                stage=db_task["stage"] or "",
                progress=db_task["progress"],
                video_url=f"/api/video/{task_id}",
                srt_download_url=db_task.get("srt_download_url") or f"/api/download/{task_id}",
                error=db_task.get("error"),
                subtitles=subs,
            )
            tasks[task_id] = task
            return task
    except Exception as e:
        logger.warning(f"Failed to restore task {task_id} from PostgreSQL: {e}")

    # Fallback to local persistent disk state
    state_file = PROCESSED_DIR / f"{task_id}_state.json"
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                task_dict = json.load(f)
            tasks[task_id] = TaskStatus(**task_dict)
            srt_path = PROCESSED_DIR / f"{task_id}.srt"
            if srt_path.exists():
                task_srt_paths[task_id] = srt_path
            return tasks[task_id]
        except Exception as e:
            logger.warning(f"Could not restore state from {state_file}: {e}")

    return None


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """Returns task execution progress, stage, and subtitle segments from memory, DB, or disk."""
    cached = tasks.get(task_id)
    if cached is not None:
        # Recover if earlier load cached empty subtitles while an .srt file exists on disk
        if cached.status == "COMPLETED" and not cached.subtitles:
            restored = await run_in_threadpool(_restore_task_status_sync, task_id)
            if restored:
                return restored
        return cached

    restored = await run_in_threadpool(_restore_task_status_sync, task_id)
    if restored is not None:
        return restored
    raise HTTPException(status_code=404, detail="Task not found")


@router.post("/tasks/{task_id}/resume", response_model=Dict[str, str])
async def resume_task(task_id: str, background_tasks: BackgroundTasks):
    """Resumes an interrupted task if video file exists on disk."""
    video_matches = list(UPLOAD_DIR.glob(f"{task_id}_*"))
    if not video_matches:
        raise HTTPException(status_code=404, detail="Original video file not found for this task.")
    
    video_path = video_matches[0]
    filename = video_path.name.replace(f"{task_id}_", "", 1)
    task_video_paths[task_id] = video_path

    if task_id in tasks and tasks[task_id].status == "PROCESSING":
        return {"task_id": task_id, "message": "Task is already actively processing."}

    tasks[task_id] = TaskStatus(
        task_id=task_id,
        status="PROCESSING",
        stage="중단된 작업 이어하기 준비 중...",
        progress=20,
        filename=filename,
        video_url=f"/api/video/{task_id}"
    )
    save_task_state(task_id)
    background_tasks.add_task(run_pipeline, task_id, video_path, filename)
    return {"task_id": task_id, "message": "작업이 이어하기 모드로 재개되었습니다."}


@router.put("/tasks/{task_id}/subtitles", response_model=TaskStatus)
async def update_subtitles(task_id: str, payload: UpdateSubtitlesRequest):
    """
    Allows user to save inline edits made in the frontend.
    Re-generates the .srt file with edited content so downloading yields updated subtitles.
    """
    if task_id not in tasks:
        # Load from DB if needed
        await get_task_status(task_id)
        if task_id not in tasks:
            raise HTTPException(status_code=404, detail="Task not found")
    
    task = tasks[task_id]

    # Re-generate SRT file with new subtitles (preserve user-edited timings without duplicate +0.3s extension)
    raw_segments_dict = [sub.model_dump() for sub in payload.subtitles]
    clean_segments = [s for s in raw_segments_dict if (s.get("refined_text") or s.get("text") or s.get("raw_text") or "").strip()]
    if clean_segments:
        segments_dict = optimize_subtitle_timing(clean_segments, extend_sec=0.0)
    else:
        segments_dict = []
    task.subtitles = [SubtitleSegment(**seg) for seg in segments_dict]
    
    srt_path = PROCESSED_DIR / f"{task_id}.srt"
    generate_srt_file(segments_dict, srt_path, optimize=False)
    task_srt_paths[task_id] = srt_path

    # Persist updated subtitles to PostgreSQL
    try:
        db.save_subtitles(task_id, segments_dict)
        # CRITICAL: Also update completed_tasks so subtitle_count and srt_path reflect newly added subtitles!
        task_type = "translator" if (task.filename and task.filename.endswith(".srt")) else "studio"
        db.add_completed_task(
            task_id=task_id,
            filename=task.filename or f"task_{task_id[:8]}",
            subtitle_count=len(segments_dict),
            srt_path=str(srt_path),
            srt_download_url=f"/api/download/{task_id}",
            task_type=task_type
        )
    except Exception as e:
        logger.warning(f"Failed to persist edited subtitles to PostgreSQL: {e}")

    save_task_state(task_id)
    return task


@router.get("/download/{task_id}")
async def download_srt(task_id: str):
    """Provides standard .srt file download matching original video filename."""
    srt_path = task_srt_paths.get(task_id)
    if not srt_path or not srt_path.exists():
        # 1. Check DB (transm_tasks)
        db_task = db.get_task(task_id)
        if db_task and db_task.get("srt_path") and Path(db_task["srt_path"]).exists():
            srt_path = Path(db_task["srt_path"])
            task_srt_paths[task_id] = srt_path
        else:
            # 2. Check completed_tasks table
            try:
                from sqlalchemy import text
                with db.get_engine().connect() as conn:
                    res = conn.execute(text("SELECT srt_path FROM completed_tasks WHERE task_id = :tid"), {"tid": task_id}).scalar()
                    if res and Path(res).exists():
                        srt_path = Path(res)
                        task_srt_paths[task_id] = srt_path
            except Exception:
                pass

        # 3. Fallback to PROCESSED_DIR
        if not srt_path or not srt_path.exists():
            fallback_srt = PROCESSED_DIR / f"{task_id}.srt"
            if fallback_srt.exists():
                srt_path = fallback_srt
                task_srt_paths[task_id] = srt_path
            else:
                raise HTTPException(status_code=404, detail="Subtitles file not found or not ready")

    if srt_path.exists() and srt_path.stat().st_size == 0:
        raise HTTPException(status_code=400, detail="생성된 자막이 없어 다운로드할 수 없습니다. 상세 보기에서 자막을 추가해 주세요.")

    # Determine original filename from memory or PostgreSQL
    task = tasks.get(task_id)
    filename = task.filename if task else None
    if not filename:
        db_task = db.get_task(task_id)
        if db_task and db_task.get("filename"):
            filename = db_task["filename"]

    base_name = Path(filename).stem if filename else task_id
    if base_name.endswith(".srt"):
        base_name = Path(base_name).stem
    # If filename has a translation language suffix (e.g. _ko), strip it to match original video filename
    for lang_code in ["_ko", "_en", "_ja", "_zh", "_es"]:
        if base_name.endswith(lang_code):
            base_name = base_name[:-len(lang_code)]
            break
    download_filename = f"{base_name}.srt"
    encoded_filename = urllib.parse.quote(download_filename, encoding="utf-8")
    content_disposition = f'attachment; filename="subtitles.srt"; filename*=UTF-8\'\'{encoded_filename}'

    # Increment download count in PostgreSQL
    try:
        db.increment_download_count(task_id)
    except Exception as e:
        logger.warning(f"Failed to record download count for {task_id}: {e}")

    return FileResponse(
        path=srt_path,
        media_type="application/x-subrip",
        headers={
            "Content-Disposition": content_disposition,
            "Access-Control-Expose-Headers": "Content-Disposition",
        }
    )


@router.post("/tasks/{task_id}/download-track")
async def track_download(task_id: str):
    """Explicitly records that a task has been downloaded."""
    count = db.increment_download_count(task_id)
    return {"task_id": task_id, "download_count": count, "downloaded": True}


class BatchDownloadRequest(BaseModel):
    task_ids: Optional[List[str]] = None
    task_type: Optional[str] = None
    undownloaded_only: Optional[bool] = False


def _build_zip_archive_sync(eligible_tasks: List[Dict[str, Any]]) -> tuple[bytes, List[str]]:
    """Synchronous CPU/disk bound worker that builds the ZIP file in threadpool."""
    zip_buffer = io.BytesIO()
    used_entry_names: set[str] = set()
    downloaded_ids: List[str] = []

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for t in eligible_tasks:
            t_id = t["task_id"]
            raw_fn = t.get("filename") or f"subtitles_{t_id[:8]}"

            base_name = Path(raw_fn).stem
            if base_name.endswith(".srt"):
                base_name = Path(base_name).stem
            for lang_code in ["_ko", "_en", "_ja", "_zh", "_es"]:
                if base_name.endswith(lang_code):
                    base_name = base_name[:-len(lang_code)]
                    break

            safe_base = re.sub(r'[\\/*?:"<>|]', '_', base_name).strip() or f"subtitles_{t_id[:8]}"
            entry_name = f"{safe_base}.srt"

            counter = 1
            while entry_name in used_entry_names:
                entry_name = f"{safe_base} ({counter}).srt"
                counter += 1
            used_entry_names.add(entry_name)

            srt_bytes = b""
            srt_path = task_srt_paths.get(t_id) or (PROCESSED_DIR / f"{t_id}.srt")
            if not srt_path.exists() and t.get("srt_path"):
                srt_path = Path(t["srt_path"])

            if srt_path.exists():
                try:
                    srt_bytes = srt_path.read_bytes()
                except Exception as read_err:
                    logger.warning(f"Error reading SRT file for {t_id}: {read_err}")

            if not srt_bytes:
                try:
                    _, segments = load_segments_from_task(t_id)
                    if segments:
                        optimized = optimize_subtitle_timing(segments)
                        out = io.StringIO()
                        for idx, seg in enumerate(optimized, start=1):
                            s_start = seg.get("start_str") or "00:00:00,000"
                            s_end = seg.get("end_str") or "00:00:05,000"
                            s_text = seg.get("refined_text") or seg.get("text") or ""
                            out.write(f"{idx}\n{s_start} --> {s_end}\n{s_text}\n\n")
                        srt_bytes = out.getvalue().encode("utf-8-sig")
                except Exception as gen_err:
                    logger.warning(f"Error generating fallback SRT for {t_id}: {gen_err}")

            if srt_bytes:
                # Ensure UTF-8 BOM for maximum compatibility with players like Series On
                if not srt_bytes.startswith(b'\xef\xbb\xbf'):
                    srt_bytes = b'\xef\xbb\xbf' + srt_bytes
                zinfo = zipfile.ZipInfo(filename=entry_name, date_time=datetime.now().timetuple()[:6])
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(zinfo, srt_bytes)
                downloaded_ids.append(t_id)

    return zip_buffer.getvalue(), downloaded_ids


async def _execute_batch_download(
    req: Optional[BatchDownloadRequest],
    undownloaded_only: bool
):
    target_ids = req.task_ids if req and req.task_ids else None
    task_type_filter = req.task_type if req and req.task_type else None

    # Retrieve completed tasks (filter out 0-subtitle tasks from batch downloads)
    all_completed = await run_in_threadpool(db.get_completed_tasks, limit=50000, task_type=task_type_filter)
    all_completed = [t for t in all_completed if (t.get("subtitle_count") or 0) > 0]

    if undownloaded_only:
        eligible_tasks = [
            t for t in all_completed
            if (t.get("download_count") or 0) == 0 and not t.get("downloaded")
        ]
    else:
        eligible_tasks = all_completed

    if target_ids is not None:
        target_id_set = set(target_ids)
        eligible_tasks = [t for t in eligible_tasks if t["task_id"] in target_id_set]

    if not eligible_tasks:
        if undownloaded_only:
            msg = "다운로드 대상인 미다운로드 작업이 없습니다. 이미 모든 자막을 다운로드했거나 대상이 존재하지 않습니다."
        else:
            msg = "일괄 다운로드할 완료 작업이 없습니다."
        raise HTTPException(status_code=400, detail=msg)

    # Build ZIP archive in worker threadpool to avoid blocking FastAPI event loop
    zip_bytes, downloaded_ids = await run_in_threadpool(_build_zip_archive_sync, eligible_tasks)

    if not downloaded_ids:
        raise HTTPException(status_code=404, detail="다운로드할 수 있는 자막 파일을 찾을 수 없습니다.")

    # Increment download count and update timestamp for each task
    for t_id in downloaded_ids:
        try:
            await run_in_threadpool(db.increment_download_count, t_id)
        except Exception as e:
            logger.warning(f"Failed to increment download count for {t_id}: {e}")

    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "transm_undownloaded" if undownloaded_only else "transm_all_subtitles"
    zip_filename = f"{prefix}_{now_str}.zip"
    encoded_filename = urllib.parse.quote(zip_filename, encoding="utf-8")
    content_disposition = f'attachment; filename="transm_subtitles.zip"; filename*=UTF-8\'\'{encoded_filename}'

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition,
            "Access-Control-Expose-Headers": "Content-Disposition, X-Downloaded-Count",
            "X-Downloaded-Count": str(len(downloaded_ids)),
        }
    )


@router.post("/download/batch-all")
async def batch_download_all(req: Optional[BatchDownloadRequest] = None):
    """
    Creates and streams a ZIP file containing .srt files for all completed tasks in batch,
    regardless of previous download history.
    Increments download count for each included task.
    """
    return await _execute_batch_download(req, undownloaded_only=False)


@router.get("/download/batch-all")
async def batch_download_all_get(task_type: Optional[str] = None):
    """GET variant of batch download for all completed items."""
    req = BatchDownloadRequest(task_type=task_type)
    return await _execute_batch_download(req, undownloaded_only=False)


@router.post("/download/batch-undownloaded")
async def batch_download_undownloaded(req: Optional[BatchDownloadRequest] = None):
    """
    Creates and streams a ZIP file containing .srt files strictly for completed tasks
    that have NOT yet been downloaded (download_count == 0).
    Atomically increments download_count for each task successfully packaged into the ZIP.
    """
    return await _execute_batch_download(req, undownloaded_only=True)


@router.get("/download/batch-undownloaded")
async def batch_download_undownloaded_get(task_type: Optional[str] = None):
    """GET variant of batch download for all un-downloaded items."""
    req = BatchDownloadRequest(task_type=task_type)
    return await _execute_batch_download(req, undownloaded_only=True)


@router.get("/video/{task_id}")
async def get_video(task_id: str):
    """Streams the video file so react-player can preview it with web compatibility."""
    # 1. Prefer web-compatible H.264 MP4 preview if available
    preview_path = PROCESSED_DIR / f"{task_id}_preview.mp4"
    if preview_path.exists() and preview_path.stat().st_size > 0:
        return FileResponse(path=preview_path, media_type="video/mp4")

    # 2. Locate original uploaded or indexed video without blocking event loop
    video_path = task_video_paths.get(task_id)
    if not video_path or not video_path.exists():
        matches = list(UPLOAD_DIR.glob(f"{task_id}_*"))
        if matches and matches[0].exists():
            video_path = matches[0]
            task_video_paths[task_id] = video_path
        else:
            task = tasks.get(task_id)
            if not task:
                try:
                    task = await get_task_status(task_id)
                except Exception:
                    task = None
            video_path = task_video_paths.get(task_id)
            if (not video_path or not video_path.exists()) and task and task.filename:
                found = await run_in_threadpool(find_video_file_on_server, task.filename)
                if found and found.exists():
                    video_path = found
                    task_video_paths[task_id] = video_path

    if not video_path or not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    ext = video_path.suffix.lower()
    # 3. If WMV/ASF/AVI, kick off non-blocking background preview generation and return immediately
    if ext in ['.wmv', '.asf', '.avi']:
        if not preview_path.exists():
            schedule_web_preview(task_id, video_path, preview_path)
        else:
            return FileResponse(path=preview_path, media_type="video/mp4")
        mime = "video/x-ms-wmv" if ext in ['.wmv', '.asf'] else "video/x-msvideo"
        return FileResponse(path=video_path, media_type=mime)

    media_type = "video/webm" if ext == '.webm' else "video/mp4"
    return FileResponse(path=video_path, media_type=media_type)


class BatchDeleteRequest(BaseModel):
    task_ids: List[str]


def purge_task_files_and_cache(task_id: str) -> int:
    """Helper to remove all disk files and memory cache for a given task_id."""
    deleted_count = 0
    # 1. Clean up UPLOAD_DIR
    for vf in UPLOAD_DIR.glob(f"{task_id}*"):
        try:
            if vf.is_file():
                vf.unlink()
                deleted_count += 1
        except Exception as e:
            logger.warning(f"Failed to delete upload file {vf}: {e}")

    # 2. Clean up PROCESSED_DIR (wav, srt, raw.json, checkpoint.json, state.json, mp4 web preview)
    for pf in PROCESSED_DIR.glob(f"{task_id}*"):
        try:
            if pf.is_file():
                pf.unlink()
                deleted_count += 1
        except Exception as e:
            logger.warning(f"Failed to delete processed file {pf}: {e}")

    # 3. Clean up in-memory caches
    tasks.pop(task_id, None)
    task_video_paths.pop(task_id, None)
    task_srt_paths.pop(task_id, None)

    # 4. Clean up queue references
    try:
        db.delete_studio_queue_item(task_id)
        db.delete_studio_queue_item(f"studio_{task_id}")
    except Exception:
        pass

    return deleted_count


@router.delete("/tasks/all")
async def delete_all_tasks_endpoint(task_type: Optional[str] = None):
    """
    Deletes all tasks (optionally filtered by task_type) and purges all generated subtitles and associated files.
    """
    actual_type = None if not task_type or task_type == 'all' else task_type
    db_deleted_ids = db.delete_all_tasks(task_type=actual_type)
    all_target_ids = set(db_deleted_ids)

    # Also collect any in-memory tasks
    for tid, tdata in list(tasks.items()):
        if not actual_type or tdata.get("task_type") == actual_type:
            all_target_ids.add(tid)

    total_files_deleted = 0
    for tid in all_target_ids:
        total_files_deleted += purge_task_files_and_cache(tid)

    # If deleting without filter (all tabs), wipe all remaining .srt, .wav, .json files in PROCESSED_DIR
    if not actual_type:
        for ext in ("*.srt", "*.wav", "*.json", "*_preview.mp4"):
            for orphan in PROCESSED_DIR.glob(ext):
                try:
                    if orphan.is_file():
                        orphan.unlink()
                        total_files_deleted += 1
                except Exception as e:
                    logger.warning(f"Failed to purge orphan file {orphan}: {e}")

    return {
        "deleted_count": len(all_target_ids),
        "deleted_files_count": total_files_deleted,
        "message": f"총 {len(all_target_ids)}개 작업 및 생성된 모든 자막과 미디어 파일이 완전히 삭제되었습니다."
    }


@router.post("/tasks/batch-delete")
async def batch_delete_tasks_endpoint(payload: BatchDeleteRequest):
    """
    Deletes a specified batch of tasks and purges their generated subtitles and associated files.
    """
    task_ids = payload.task_ids
    if not task_ids:
        return {"deleted_count": 0, "message": "삭제할 작업 ID 목록이 비어 있습니다."}

    db.delete_tasks_batch(task_ids)

    total_files_deleted = 0
    for tid in task_ids:
        total_files_deleted += purge_task_files_and_cache(tid)

    return {
        "deleted_count": len(task_ids),
        "deleted_files_count": total_files_deleted,
        "message": f"선택한 {len(task_ids)}개 작업 및 관련 자막 파일이 모두 삭제되었습니다."
    }


@router.delete("/tasks/{task_id}")
async def delete_task_endpoint(task_id: str):
    """
    Deletes task from DB and purges all associated files:
    - Uploaded video files: UPLOAD_DIR / f"{task_id}*"
    - Audio and processed files: PROCESSED_DIR / f"{task_id}*"
    - Memory cache: tasks, task_video_paths, task_srt_paths
    """
    files_deleted = purge_task_files_and_cache(task_id)
    try:
        db.delete_task(task_id)
    except Exception as e:
        logger.warning(f"DB deletion error for task {task_id}: {e}")

    return {
        "task_id": task_id,
        "deleted": True,
        "deleted_files_count": files_deleted,
        "message": "작업 및 관련 파일이 모두 성공적으로 삭제되었습니다."
    }



def run_translation_pipeline(
    trans_task_id: str,
    segments: List[Dict[str, Any]],
    filename: str,
    target_lang: str = "ko"
):
    """Background worker executing translation of subtitle segments."""
    try:
        target_name = TARGET_LANG_NAMES.get(target_lang, target_lang)
        active_cfg = get_active_llm_config()
        prov_name = active_cfg.get("provider", "ollama").upper()
        model_name = active_cfg.get("model", "gemma4:12b")
        tasks[trans_task_id].stage = f"{prov_name} ({model_name}) 모델로 {target_name} 번역 준비 중..."
        tasks[trans_task_id].progress = 10
        save_task_state(trans_task_id)

        checkpoint_path = PROCESSED_DIR / f"{trans_task_id}_checkpoint.json"
        initial_cp = None
        try:
            initial_cp = db.get_checkpoint_segments(trans_task_id)
        except Exception:
            pass
        if not initial_cp and checkpoint_path.exists():
            try:
                with open(checkpoint_path, "r", encoding="utf-8") as f:
                    initial_cp = json.load(f)
            except Exception:
                pass

        def on_trans_progress(current_batch: int, total_batches: int):
            pct = 10 + int((current_batch / total_batches) * 80)
            tasks[trans_task_id].progress = min(pct, 95)
            cfg = get_active_llm_config()
            cur_prov = cfg.get("provider", "ollama").upper()
            cur_model = cfg.get("model", "gemma4:12b")
            tasks[trans_task_id].stage = f"{cur_prov} ({cur_model}) 자막 {target_name} 번역 중... ({current_batch}/{total_batches} 완료)"
            save_task_state(trans_task_id)

        def on_checkpoint(cp_map):
            try:
                db.save_checkpoint_segments(trans_task_id, cp_map)
                with open(checkpoint_path, "w", encoding="utf-8") as f:
                    json.dump(cp_map, f, ensure_ascii=False)
            except Exception:
                pass

        translated = translate_subtitles_list(
            segments,
            target_lang=target_lang,
            initial_checkpoint=initial_cp,
            progress_callback=on_trans_progress,
            checkpoint_callback=on_checkpoint
        )

        translated = optimize_subtitle_timing(translated)

        tasks[trans_task_id].stage = "번역된 SRT 파일 생성 중..."
        tasks[trans_task_id].progress = 95
        save_task_state(trans_task_id)

        srt_path = PROCESSED_DIR / f"{trans_task_id}.srt"
        generate_srt_file(translated, srt_path)
        task_srt_paths[trans_task_id] = srt_path

        sub_models = [SubtitleSegment(**seg) for seg in translated]
        sub_dicts = [seg if isinstance(seg, dict) else seg.model_dump() for seg in translated]

        try:
            db.save_subtitles(trans_task_id, sub_dicts)
            db.add_completed_task(
                task_id=trans_task_id,
                filename=filename,
                subtitle_count=len(sub_models),
                srt_path=str(srt_path),
                srt_download_url=f"/api/download/{trans_task_id}",
                task_type="translator"
            )
        except Exception as e:
            logger.warning(f"Failed to record completed translation: {e}")

        tasks[trans_task_id].subtitles = sub_models
        tasks[trans_task_id].srt_download_url = f"/api/download/{trans_task_id}"
        tasks[trans_task_id].status = "COMPLETED"
        tasks[trans_task_id].stage = f"자막 {target_name} 번역 완료"
        tasks[trans_task_id].progress = 100
        save_task_state(trans_task_id)
        logger.info(f"Translation task {trans_task_id} completed successfully.")

    except Exception as e:
        logger.exception(f"Translation pipeline error: {e}")
        tasks[trans_task_id].status = "FAILED"
        tasks[trans_task_id].stage = "번역 중 오류 발생"
        tasks[trans_task_id].error = str(e)
        save_task_state(trans_task_id)


def load_segments_from_task(task_id: str) -> tuple[str, List[Dict[str, Any]]]:
    """Helper to retrieve segments from in-memory cache, DB, or SRT file on disk."""
    filename = "subtitles.srt"
    segments: List[Dict[str, Any]] = []

    # 1. Check in-memory tasks
    if task_id in tasks and tasks[task_id].subtitles:
        filename = tasks[task_id].filename
        segments = [s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in tasks[task_id].subtitles]
        return filename, segments

    # 2. Check DB
    try:
        db_task = db.get_task(task_id)
        if db_task:
            filename = db_task.get("filename", filename)
            subs_raw = db_task.get("subtitles") or []
            if isinstance(subs_raw, str):
                subs_raw = json.loads(subs_raw)
            if subs_raw:
                return filename, subs_raw
    except Exception as e:
        logger.warning(f"Error loading task from DB: {e}")

    # 2-b. Check DB raw_segments (Whisper STT or source segments for translation)
    try:
        raw_segs = db.get_raw_segments(task_id)
        if raw_segs:
            return filename, raw_segs
    except Exception as e:
        logger.warning(f"Error loading raw segments from DB: {e}")

    # 2-c. Check disk raw JSON file
    disk_raw_file = PROCESSED_DIR / f"{task_id}_raw.json"
    if disk_raw_file.exists():
        try:
            with open(disk_raw_file, "r", encoding="utf-8") as f:
                raw_segs = json.load(f)
            if raw_segs:
                return filename, raw_segs
        except Exception as e:
            logger.warning(f"Error reading disk raw json: {e}")

    # 3. Check disk SRT file
    srt_file = PROCESSED_DIR / f"{task_id}.srt"
    if not srt_file.exists():
        try:
            completed_list = db.get_completed_tasks()
            for ct in completed_list:
                if ct.get("task_id") == task_id:
                    filename = ct.get("filename", filename)
                    if ct.get("srt_path") and Path(ct["srt_path"]).exists():
                        srt_file = Path(ct["srt_path"])
                        break
        except Exception:
            pass

    if srt_file.exists():
        try:
            segments.extend(parse_srt_segments_multi_encoding(srt_file))
        except Exception as e:
            logger.warning(f"Error parsing srt file on disk: {e}")

    # 4. Fallback: check if this translation task originated from a parent video task
    if not segments:
        try:
            db_task = db.get_task(task_id)
            if db_task and db_task.get("video_path"):
                v_path = Path(db_task["video_path"])
                parent_id = v_path.stem.split("_")[0]
                if parent_id and parent_id != task_id:
                    _, parent_segments = load_segments_from_task(parent_id)
                    if parent_segments:
                        return filename, parent_segments
        except Exception:
            pass

    return filename, segments


@router.get("/translate/active")
async def get_active_translation_task():
    """
    Returns the currently active (PROCESSING) translation task if one exists.
    Checks memory and PostgreSQL DB so page refresh immediately resumes monitoring.
    """
    # 1. Check in-memory tasks (prioritize the task with furthest progress)
    active_in_mem = [
        t for t in tasks.values()
        if t.status == "PROCESSING" and ("번역" in (t.stage or "") or "_ko." in t.filename or "_en." in t.filename or "_ja." in t.filename or "_zh." in t.filename or t.filename.endswith(".srt"))
    ]
    if active_in_mem:
        best_task = max(active_in_mem, key=lambda x: x.progress)
        return {
            "active": True,
            "task": best_task
        }

    # 2. Check PostgreSQL database
    try:
        all_db_tasks = db.get_all_tasks(limit=10)
        active_db = []
        for dbt in all_db_tasks:
            if dbt.get("status") == "PROCESSING":
                fname = dbt.get("filename", "")
                stage = dbt.get("stage", "")
                if "번역" in stage or "_ko." in fname or fname.endswith(".srt"):
                    tid = dbt["task_id"]
                    if tid not in tasks:
                        tasks[tid] = TaskStatus(
                            task_id=tid,
                            filename=fname,
                            status="PROCESSING",
                            stage=stage,
                            progress=dbt.get("progress", 0),
                            video_url=f"/api/video/{tid}",
                            error=dbt.get("error")
                        )
                    active_db.append(tasks[tid])
        if active_db:
            best_db = max(active_db, key=lambda x: x.progress)
            return {
                "active": True,
                "task": best_db
            }
    except Exception as e:
        logger.warning(f"Error querying active translation task from DB: {e}")

    return {
        "active": False,
        "task": None
    }


@router.get("/active-summary")
async def get_active_summary():
    """
    Returns counts and details of active processing tasks in Studio and Translator.
    Used by Sidebar and global queue indicators.
    """
    studio_active = []
    translator_active = []

    # 1. From memory
    for tid, t in tasks.items():
        if t.status == "PROCESSING":
            if "번역" in (t.stage or "") or (t.filename and (t.filename.endswith(".srt") or "_ko." in t.filename)):
                translator_active.append(t)
            else:
                studio_active.append(t)

    # 2. Check DB if memory empty
    if not studio_active and not translator_active:
        try:
            db_tasks = db.get_all_tasks(limit=20)
            for dbt in db_tasks:
                if dbt.get("status") == "PROCESSING":
                    fname = dbt.get("filename", "")
                    stage = dbt.get("stage", "")
                    tid = dbt["task_id"]
                    t_obj = tasks.get(tid) or TaskStatus(
                        task_id=tid,
                        filename=fname,
                        status="PROCESSING",
                        stage=stage,
                        progress=dbt.get("progress", 0),
                        video_url=f"/api/video/{tid}"
                    )
                    if "번역" in stage or fname.endswith(".srt") or "_ko." in fname:
                        translator_active.append(t_obj)
                    else:
                        studio_active.append(t_obj)
        except Exception:
            pass

    return {
        "studio": {
            "active": len(studio_active) > 0,
            "count": len(studio_active),
            "tasks": studio_active
        },
        "translator": {
            "active": len(translator_active) > 0,
            "count": len(translator_active),
            "tasks": translator_active
        }
    }


class StudioQueueSyncRequest(BaseModel):
    client_id: Optional[str] = None
    items: List[Dict[str, Any]] = []


@router.get("/studio-queue")
async def get_studio_queue_endpoint():
    """
    Returns the unified studio queue including currently processing tasks on server
    and all waiting/queued items so any browser or tab can see active and waiting items.
    """
    db_items = db.get_studio_queue()

    # 0. Build lookup of completed tasks so any finished tasks in queue reflect immediately
    completed_task_ids = set()
    completed_filenames = set()
    try:
        recent_completed = db.get_completed_tasks(limit=50000)
        for ct in recent_completed:
            if ct.get("task_id"):
                completed_task_ids.add(ct["task_id"])
            if ct.get("filename"):
                completed_filenames.add(ct["filename"])
    except Exception:
        pass

    # 1. Identify active studio task on server
    active_server_task: Optional[TaskStatus] = None
    for tid, t in tasks.items():
        if t.status in ("PROCESSING", "PENDING"):
            if not ("번역" in (t.stage or "") or (t.filename and t.filename.endswith(".srt"))):
                active_server_task = t
                break

    if not active_server_task:
        try:
            recent_tasks = db.get_all_tasks(limit=10)
            for rt in recent_tasks:
                if rt.get("status") in ("PROCESSING", "PENDING"):
                    fname = rt.get("filename", "")
                    stage = rt.get("stage", "")
                    if not ("번역" in stage or fname.endswith(".srt")):
                        tid = rt["task_id"]
                        active_server_task = tasks.get(tid) or TaskStatus(
                            task_id=tid,
                            filename=fname,
                            status=rt.get("status", "PROCESSING"),
                            stage=stage,
                            progress=rt.get("progress", 0),
                            video_url=f"/api/video/{tid}"
                        )
                        break
        except Exception:
            pass

    # 2. Build synthesized queue combining DB items with active server task
    queue = []
    seen_task_ids = set()
    active_item_dict = None
    active_matched = False

    for it in db_items:
        qid = it["id"]
        tid = it.get("task_id")
        fname = it.get("filename")
        status = it.get("status", "WAITING")
        task_data = None

        # Check if this DB item corresponds to the active server task
        is_active_match = False
        if active_server_task:
            if tid and tid == active_server_task.task_id:
                is_active_match = True
            elif not active_matched and fname == active_server_task.filename and status != "COMPLETED":
                is_active_match = True
                tid = active_server_task.task_id
                try:
                    db.update_queue_item_task_link(qid, active_server_task.task_id, active_server_task.status)
                except Exception:
                    pass

        # Check if this item is already completed in completed_tasks (only if not active server task)
        if not is_active_match:
            is_already_completed = bool(tid and tid in completed_task_ids)
            if is_already_completed or status == "COMPLETED":
                try:
                    db.delete_studio_queue_item(qid)
                except Exception:
                    pass
                continue

        if is_active_match and active_server_task:
            active_matched = True
            seen_task_ids.add(active_server_task.task_id)
            status = active_server_task.status
            task_data = {
                "task_id": active_server_task.task_id,
                "status": active_server_task.status,
                "stage": active_server_task.stage,
                "progress": active_server_task.progress,
                "filename": active_server_task.filename,
                "error": active_server_task.error,
                "video_url": active_server_task.video_url,
                "subtitles": []
            }
        elif tid:
            seen_task_ids.add(tid)
            if tid in tasks:
                t = tasks[tid]
                status = t.status
                task_data = {
                    "task_id": t.task_id,
                    "status": t.status,
                    "stage": t.stage,
                    "progress": t.progress,
                    "filename": t.filename,
                    "error": t.error,
                    "video_url": t.video_url,
                    "subtitles": []
                }
            else:
                dbt = db.get_task(tid)
                if dbt:
                    status = dbt.get("status", status)
                    task_data = {
                        "task_id": dbt.get("task_id"),
                        "status": dbt.get("status"),
                        "stage": dbt.get("stage"),
                        "progress": dbt.get("progress"),
                        "filename": dbt.get("filename"),
                        "error": dbt.get("error"),
                        "video_url": dbt.get("video_url"),
                        "subtitles": []
                    }

        # If task status resolved to COMPLETED, remove from studio queue and omit from response
        if status == "COMPLETED":
            try:
                db.delete_studio_queue_item(qid)
            except Exception:
                pass
            continue

        resolved_error = it.get("error") or (task_data.get("error") if task_data else None)

        item_dict = {
            "id": qid,
            "filename": it["filename"],
            "size": it.get("size", 0),
            "status": status,
            "uploadProgress": 100 if (status in ("PROCESSING", "COMPLETED") or is_active_match) else it.get("upload_progress", 0),
            "taskId": tid,
            "taskData": task_data,
            "error": resolved_error,
            "addedAt": it.get("added_at"),
            "clientId": it.get("client_id")
        }

        if (is_active_match or (status in ("PROCESSING", "UPLOADING") and not active_item_dict)) and status != "COMPLETED":
            active_item_dict = item_dict

        queue.append(item_dict)

    # 3. If there is an active server task not present in db_items, prepend it!
    if active_server_task and active_server_task.task_id not in seen_task_ids:
        active_item_dict = {
            "id": f"studio_active_{active_server_task.task_id[:8]}",
            "filename": active_server_task.filename or "영상 분석 중",
            "size": 0,
            "status": active_server_task.status,
            "uploadProgress": 100,
            "taskId": active_server_task.task_id,
            "taskData": {
                "task_id": active_server_task.task_id,
                "status": active_server_task.status,
                "stage": active_server_task.stage,
                "progress": active_server_task.progress,
                "filename": active_server_task.filename,
                "error": active_server_task.error,
                "video_url": active_server_task.video_url,
                "subtitles": []
            },
            "error": active_server_task.error,
            "addedAt": datetime.now().isoformat(),
            "clientId": "server"
        }
        queue.insert(0, active_item_dict)

    # If activeItem exists, ensure it is designated as activeItem
    if active_server_task and not active_item_dict:
        active_item_dict = next((it for it in queue if it.get("taskId") == active_server_task.task_id and it.get("status") != "COMPLETED"), None)

    waiting_count = sum(1 for it in queue if it.get("status") == "WAITING")
    is_busy = active_item_dict is not None

    return {
        "activeItem": active_item_dict,
        "waitingCount": waiting_count,
        "isBusy": is_busy,
        "queue": queue
    }


@router.post("/studio-queue/sync")
async def sync_studio_queue_endpoint(payload: StudioQueueSyncRequest):
    """Syncs the queue items from a client browser to the server database."""
    if payload.items:
        db.upsert_studio_queue_items(payload.items, client_id=payload.client_id)
    return await get_studio_queue_endpoint()


@router.delete("/studio-queue/{queue_id}")
async def delete_studio_queue_endpoint(queue_id: str):
    """Deletes an item from the studio queue."""
    db.delete_studio_queue_item(queue_id)
    return {"deleted": True, "queue_id": queue_id}


@router.post("/studio-queue/clear-completed")
async def clear_completed_studio_queue_endpoint():
    """Clears completed or failed items from studio queue."""
    db.clear_completed_studio_queue()
    return {"cleared": True}


@router.post("/studio-queue/start-next")
async def start_next_queue_item_endpoint(background_tasks: BackgroundTasks):
    """
    Checks the studio queue for the next WAITING item.
    If the video file already exists on the server (in UPLOAD_DIR or local media folders),
    automatically launches the pipeline and marks it PROCESSING!
    """
    res = auto_start_next_waiting_item(background_tasks)
    return res or {"started": False, "message": "대기 중인 작업이 없습니다."}


class ScanFolderRequest(BaseModel):
    folder_path: str
    client_id: Optional[str] = None


def _natural_sort_key(text_val: str):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", text_val)]


def _browse_folders_sync(target_dir: Path) -> tuple[List[Dict[str, str]], int]:
    """Scans direct entries in folder using worker thread."""
    folders = []
    direct_video_count = 0
    for entry in target_dir.iterdir():
        try:
            if entry.is_dir() and not entry.name.startswith("$"):
                folders.append({"name": entry.name, "path": str(entry)})
            elif entry.is_file() and entry.suffix.lower() in VALID_VIDEO_EXTENSIONS:
                direct_video_count += 1
        except Exception:
            continue
    folders.sort(key=lambda x: _natural_sort_key(x["name"]))
    return folders, direct_video_count


@router.get("/studio-queue/browse-folders")
async def browse_local_folders_endpoint(path: Optional[str] = None):
    """
    Browses local directories on the server so the user can select any folder
    and recursively queue all videos in all subfolders.
    """
    media_scan_paths = get_media_scan_dirs()
    quick_roots = []
    seen_paths = set()
    for p in media_scan_paths:
        p_str = str(p)
        if p.exists() and p.is_dir() and p_str not in seen_paths:
            label = f"{p.name} ({p})" if p.name else str(p)
            quick_roots.append({"path": p_str, "label": label})
            seen_paths.add(p_str)

    for drive in ["D:\\", "C:\\"]:
        if Path(drive).exists() and drive not in seen_paths:
            quick_roots.append({"path": drive, "label": f"로컬 디스크 ({drive})"})
            seen_paths.add(drive)

    target_str = (path or "").strip()
    if not target_str:
        return {
            "current_path": "",
            "parent_path": "",
            "quick_roots": quick_roots,
            "folders": [{"name": qr["label"], "path": qr["path"]} for qr in quick_roots],
            "direct_video_count": 0
        }

    target_dir = Path(target_str)
    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"지정한 폴더를 찾을 수 없습니다: {target_str}")

    try:
        folders, direct_video_count = await run_in_threadpool(_browse_folders_sync, target_dir)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"폴더 접근 오류: {e}")

    parent_path = str(target_dir.parent) if target_dir.parent != target_dir else ""

    return {
        "current_path": str(target_dir),
        "parent_path": parent_path,
        "quick_roots": quick_roots,
        "folders": folders,
        "direct_video_count": direct_video_count
    }


def _scan_folder_recursive_sync(root_dir: Path) -> tuple[List[Dict[str, Any]], set[str]]:
    """Worker thread scanner that recursively finds videos without blocking event loop."""
    discovered_videos = []
    subfolders_with_videos = set()

    for dirpath, _, filenames in os.walk(str(root_dir)):
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            if ext in VALID_VIDEO_EXTENSIONS:
                full_path = Path(dirpath) / fn
                try:
                    fsize = full_path.stat().st_size
                except Exception:
                    fsize = 0
                if fsize <= 0:
                    continue

                try:
                    rel_to_root = full_path.relative_to(root_dir)
                    rel_str = str(rel_to_root).replace("\\", "/")
                except Exception:
                    rel_str = fn

                if "/" in rel_str:
                    subfolders_with_videos.add(str(Path(rel_str).parent))
                    display_name = f"{root_dir.name}/{rel_str}"
                else:
                    display_name = fn

                discovered_videos.append({
                    "full_path": full_path,
                    "rel_sort_key": rel_str,
                    "display_name": display_name,
                    "base_name": fn,
                    "size": fsize
                })

    discovered_videos.sort(key=lambda x: _natural_sort_key(x["rel_sort_key"]))
    return discovered_videos, subfolders_with_videos


@router.post("/studio-queue/add-folder")
async def add_folder_to_studio_queue_endpoint(payload: ScanFolderRequest, background_tasks: BackgroundTasks):
    """
    Recursively searches the specified folder and ALL its subfolders (os.walk),
    registers every discovered video file into studio_queue_items in natural order,
    and automatically starts processing!
    """
    global _LOCAL_MEDIA_INDEX, _LOCAL_MEDIA_ALL_PATHS
    raw_path = (payload.folder_path or "").strip().strip('"').strip("'")
    if not raw_path:
        raise HTTPException(status_code=400, detail="폴더 경로를 입력하거나 선택해 주세요.")

    root_dir = Path(raw_path)
    if not root_dir.exists() or not root_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"폴더가 존재하지 않습니다: {raw_path}")

    # Run heavy directory scan off the main event loop
    discovered_videos, subfolders_with_videos = await run_in_threadpool(_scan_folder_recursive_sync, root_dir)

    if not discovered_videos:
        raise HTTPException(
            status_code=400,
            detail=f"선택한 폴더('{root_dir.name}') 및 하위 폴더에 지원되는 동영상 파일이 없습니다."
        )

    # Get existing queue to append after current items and avoid exact duplicate waiting items
    existing_items = await run_in_threadpool(db.get_studio_queue)
    existing_waiting_names = {
        it.get("filename") for it in existing_items if it.get("status") in ("WAITING", "PROCESSING", "UPLOADING")
    }
    base_order = len(existing_items)

    new_queue_items = []
    now_ms = int(time.time() * 1000)

    seen_full = {p_str for p_str, _ in _LOCAL_MEDIA_ALL_PATHS}

    for idx, vid in enumerate(discovered_videos):
        full_p: Path = vid["full_path"]
        disp_name: str = vid["display_name"]
        base_fn: str = vid["base_name"]

        # Register in server media index so find_video_file_on_server resolves it instantaneously
        _LOCAL_MEDIA_INDEX[disp_name] = full_p
        _LOCAL_MEDIA_INDEX[vid["rel_sort_key"]] = full_p
        if base_fn not in _LOCAL_MEDIA_INDEX:
            _LOCAL_MEDIA_INDEX[base_fn] = full_p
        norm_full = str(full_p).replace("\\", "/").lower()
        if norm_full not in seen_full:
            seen_full.add(norm_full)
            _LOCAL_MEDIA_ALL_PATHS.append((norm_full, full_p))

        if disp_name in existing_waiting_names or base_fn in existing_waiting_names:
            continue

        qid = f"studio_{now_ms}_{idx}_{uuid.uuid4().hex[:6]}"
        new_queue_items.append({
            "id": qid,
            "filename": disp_name,
            "size": vid["size"],
            "status": "WAITING",
            "upload_progress": 0,
            "task_id": None,
            "error": None,
            "order_index": base_order + len(new_queue_items),
            "client_id": payload.client_id or "server_folder_scan"
        })

    if new_queue_items:
        await run_in_threadpool(db.upsert_studio_queue_items, new_queue_items, client_id=payload.client_id or "server_folder_scan")

    # Immediately auto-start if idle
    try:
        auto_start_next_waiting_item(background_tasks)
    except Exception as e:
        logger.warning(f"Failed to auto-start after folder scan: {e}")

    queue_state = await get_studio_queue_endpoint()
    return {
        "added_count": len(new_queue_items),
        "total_found": len(discovered_videos),
        "subfolder_count": len(subfolders_with_videos),
        "folder_name": root_dir.name or str(root_dir),
        "queue_state": queue_state
    }



@router.post("/translate/detect")
async def detect_subtitles_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    task_id: Optional[str] = Form(None)
):
    """Auto-detects source language from uploaded .srt file or an existing completed task."""
    segments = []
    filename = "subtitles.srt"

    # Support JSON body if sent as application/json
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if not task_id and "task_id" in body:
                task_id = body["task_id"]
        except Exception:
            pass

    if file and file.filename:
        filename = file.filename
        content_bytes = await file.read()
        try:
            segments = parse_srt_bytes_multi_encoding(content_bytes)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"SRT 파일 구문 분석 실패: {e}")

    elif task_id:
        filename, segments = load_segments_from_task(task_id)
        if not segments:
            raise HTTPException(status_code=404, detail="지정한 작업의 자막을 찾을 수 없습니다.")
    else:
        raise HTTPException(status_code=400, detail="SRT 파일 업로드 또는 task_id가 필요합니다.")

    if not segments:
        raise HTTPException(status_code=400, detail="유효한 자막 항목이 없습니다.")

    lang_info = detect_subtitles_language(segments)
    return {
        "task_id": task_id,
        "filename": filename,
        "source_lang": lang_info["code"],
        "source_lang_name": lang_info["name"],
        "confidence": lang_info["confidence"],
        "total_segments": len(segments),
        "preview": segments[:6]
    }


@router.post("/translate/start", response_model=Dict[str, str], status_code=status.HTTP_202_ACCEPTED)
async def start_translation_endpoint(
    background_tasks: BackgroundTasks,
    request: Request,
    file: Optional[UploadFile] = File(None),
    task_id: Optional[str] = Form(None),
    target_lang: str = Form("ko")
):
    """Initiates an asynchronous translation pipeline into target language."""
    segments = []
    base_filename = "subtitles.srt"
    original_video_task_id = None

    # Support JSON body if sent as application/json
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if not task_id and "task_id" in body:
                task_id = body["task_id"]
            if "target_lang" in body:
                target_lang = body["target_lang"]
        except Exception:
            pass

    # Return already active translation task to prevent duplicate pipeline runs
    for tid, t in tasks.items():
        if t.status == "PROCESSING" and ("번역" in (t.stage or "") or "_ko." in t.filename or t.filename.endswith(f"_{target_lang}.srt")):
            logger.info(f"Returning already active translation task {tid}")
            return {
                "task_id": tid,
                "message": "이미 진행 중인 자막 번역 작업이 있어 해당 작업을 표시합니다."
            }

    if file and file.filename:
        base_filename = file.filename
        content_bytes = await file.read()
        try:
            segments = parse_srt_bytes_multi_encoding(content_bytes)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"SRT 파일 구문 분석 실패: {e}")
    elif task_id:
        original_video_task_id = task_id
        base_filename, segments = load_segments_from_task(task_id)
        if not segments:
            raise HTTPException(status_code=404, detail="지정한 작업의 자막을 찾을 수 없습니다.")
    else:
        raise HTTPException(status_code=400, detail="Either file or task_id is required")

    trans_task_id = str(uuid.uuid4())
    stem = Path(base_filename).stem
    # Target translated filename e.g. ipx273_ko.srt
    target_filename = f"{stem}_{target_lang}.srt"

    # Link video path if originated from an existing video task
    if original_video_task_id:
        video_matches = list(UPLOAD_DIR.glob(f"{original_video_task_id}_*"))
        if video_matches and video_matches[0].exists():
            task_video_paths[trans_task_id] = video_matches[0]

    tasks[trans_task_id] = TaskStatus(
        task_id=trans_task_id,
        status="PROCESSING",
        stage=f"자막 {target_lang} 번역 파이프라인 초기화 중...",
        progress=5,
        filename=target_filename,
        video_url=f"/api/video/{original_video_task_id}" if original_video_task_id else None
    )
    save_task_state(trans_task_id)

    # Persist input segments for crash recovery and server restarts
    try:
        db.save_raw_segments(trans_task_id, segments)
        with open(PROCESSED_DIR / f"{trans_task_id}_raw.json", "w", encoding="utf-8") as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)
    except Exception as save_err:
        logger.warning(f"Failed to persist translation source segments: {save_err}")

    background_tasks.add_task(run_translation_pipeline, trans_task_id, segments, target_filename, target_lang)

    return {
        "task_id": trans_task_id,
        "message": "자막 번역 작업이 시작되었습니다."
    }


# ==============================================================================
# Admin & System Engine Configuration Endpoints (LLM & Whisper Modes)
# ==============================================================================

RECOMMENDED_OLLAMA_MODELS = [
    {
        "name": "qwen2.5:14b",
        "label": "qwen2.5:14b (★ 최고 추천 - 동양권 한·중·일 구어체 번역 최강 14B)",
        "size_str": "9.0 GB",
        "desc": "복잡한 대화 맥락, 존댓말/반말 뉘앙스, 자연스러운 한국어 구어체 의역 성능 1위",
        "recommended": True
    },
    {
        "name": "qwen2.5:7b",
        "label": "qwen2.5:7b (★ 고속 추천 - 빠르고 자연스러운 일상 대화체 7B)",
        "size_str": "4.7 GB",
        "desc": "가벼운 VRAM 점유율과 빠른 처리 속도, 뛰어난 한·일/한·중 번역 품질",
        "recommended": True
    },
    {
        "name": "gemma4:12b",
        "label": "gemma4:12b (Google Gemma 12B 다목적 표준 모델)",
        "size_str": "8.0 GB",
        "desc": "안정적인 문법 교정 및 정돈된 자막 생성",
        "recommended": False
    },
    {
        "name": "gemma4-custom:latest",
        "label": "gemma4-custom:latest (사용자 커스텀 튜닝 모델)",
        "size_str": "8.0 GB",
        "desc": "로컬 환경에 커스텀 설정된 Gemma 계열 모델",
        "recommended": False
    },
    {
        "name": "exaone3.5:7.8b",
        "label": "exaone3.5:7.8b (LG AI 연구원 한국어 특화 모델)",
        "size_str": "4.8 GB",
        "desc": "한국어 어휘 및 자연스러운 한국어 문장 구사에 특화",
        "recommended": False
    }
]

WHISPER_MODEL_OPTIONS = [
    {
        "name": "large-v3-turbo",
        "label": "large-v3-turbo (★ 강력 추천 - 최고 수준 인식률 + 초고속 CUDA 가속)",
        "vram": "약 1.5 GB",
        "desc": "Large-v3급 음성 인식 정확도와 4배 이상 빠른 처리 속도를 동시에 제공 (RTX 4070 Ti 최적화)",
        "recommended": True
    },
    {
        "name": "large-v3",
        "label": "large-v3 (최고 정밀도 모델 - 미세 음성 및 소음 환경 강점)",
        "vram": "약 3.0 GB",
        "desc": "현존 가장 정밀한 다국어 음성 인식 모델 (처리 시간은 turbo 대비 다소 소요)",
        "recommended": False
    },
    {
        "name": "medium",
        "label": "medium (균형 잡힌 중고성능 표준 모델)",
        "vram": "약 1.5 GB",
        "desc": "준수한 다국어 인식률과 무난한 처리 속도",
        "recommended": False
    },
    {
        "name": "small",
        "label": "small (경량 고속 모델)",
        "vram": "약 500 MB",
        "desc": "빠른 인식 속도, 발음이 명확한 일반 영상에 적합",
        "recommended": False
    },
    {
        "name": "base",
        "label": "base (초경량 기본 모델 - 속도 우선, 낮은 정확도)",
        "vram": "약 150 MB",
        "desc": "가장 빠르나 작은 목소리나 빠른 외국어 발음에서 오인식이 발생할 수 있음",
        "recommended": False
    }
]

WHISPER_DEVICE_OPTIONS = [
    {
        "name": "cuda",
        "label": "NVIDIA CUDA GPU 가속 (RTX 4070 Ti) - ★ 추천",
        "desc": "GPU 텐서 코어를 활용한 초고속 음성 인식"
    },
    {
        "name": "cpu",
        "label": "CPU 전용 연산 모드",
        "desc": "GPU 메모리 부족 시 사용하는 CPU 폴백 모드"
    }
]

WHISPER_COMPUTE_OPTIONS = [
    {
        "name": "float16",
        "label": "float16 (16비트 반정밀도 - ★ CUDA GPU 표준 추천)",
        "desc": "화질/음성 손실 없는 최고 인식률 및 GPU 가속 최적화"
    },
    {
        "name": "int8_float16",
        "label": "int8_float16 (VRAM 절약형 하이브리드 양자화)",
        "desc": "VRAM 사용량을 줄이면서 속도를 유지하는 모드"
    },
    {
        "name": "int8",
        "label": "int8 (8비트 경량 양자화 - CPU 및 저사양용)",
        "desc": "메모리 사용량 최소화 모드"
    }
]


class SystemSettingsUpdateRequest(BaseModel):
    ollama_model: Optional[str] = None
    llm_batch_size: Optional[int] = None
    whisper_model_size: Optional[str] = None
    whisper_device: Optional[str] = None
    whisper_compute_type: Optional[str] = None
    llm_provider: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    requeue_completed: Optional[bool] = True


class RequeueCompletedRequest(BaseModel):
    reset_processing: Optional[bool] = False


class PullModelRequest(BaseModel):
    model_name: str


def purge_processed_cache_only(task_id: str) -> int:
    """
    Removes only generated subtitle, STT, and LLM checkpoint cache files in PROCESSED_DIR
    and clears in-memory task references, while strictly preserving original uploaded video files in UPLOAD_DIR.
    """
    deleted_count = 0
    for pf in PROCESSED_DIR.glob(f"{task_id}*"):
        try:
            if pf.is_file():
                pf.unlink()
                deleted_count += 1
        except Exception as e:
            logger.warning(f"Failed to delete processed cache file {pf}: {e}")

    tasks.pop(task_id, None)
    task_video_paths.pop(task_id, None)
    task_srt_paths.pop(task_id, None)
    return deleted_count


def execute_requeue_completed_tasks(
    reset_processing: bool = False,
    background_tasks: Optional[BackgroundTasks] = None
) -> Dict[str, Any]:
    """
    Re-registers all completed tasks back into studio_queue_items as WAITING,
    purges their old SRT/STT/LLM caches so they re-extract from the beginning with the new settings,
    and automatically starts the next waiting item if the worker is idle.
    """
    res = db.requeue_all_completed_studio_tasks(reset_processing=reset_processing)
    purged_ids = res.get("purged_task_ids", [])
    requeued_count = res.get("requeued_count", 0)

    deleted_files = 0
    for tid in purged_ids:
        deleted_files += purge_processed_cache_only(tid)

    # Also clear any COMPLETED tasks still lingering in memory
    for tid in list(tasks.keys()):
        t_obj = tasks.get(tid)
        if t_obj and (t_obj.status in ("COMPLETED", "FAILED") or reset_processing):
            tasks.pop(tid, None)
            task_srt_paths.pop(tid, None)

    start_res = auto_start_next_waiting_item(background_tasks)
    return {
        "requeued_count": requeued_count,
        "purged_task_count": len(purged_ids),
        "deleted_cache_files": deleted_files,
        "auto_started": start_res
    }


@router.post("/studio-queue/requeue-completed")
async def requeue_completed_studio_queue_endpoint(
    background_tasks: BackgroundTasks,
    payload: Optional[RequeueCompletedRequest] = None
):
    """
    Re-queues all completed studio tasks back to WAITING and restarts subtitle extraction from scratch
    using the current LLM and Whisper settings.
    """
    reset_proc = bool(payload.reset_processing) if payload and payload.reset_processing is not None else False
    result = execute_requeue_completed_tasks(reset_processing=reset_proc, background_tasks=background_tasks)
    return {
        **result,
        "message": f"기존 완료 작업 {result['requeued_count']}건이 작업 대기열(WAITING)에 다시 등록되어 변경된 설정으로 자막 재추출을 시작합니다."
    }


def _get_installed_ollama_models() -> List[Dict[str, Any]]:
    """Queries local Ollama server for currently installed models."""
    installed = []
    try:
        client = ollama.Client(host=OLLAMA_HOST)
        resp = client.list()
        models_list = resp.get("models", []) if isinstance(resp, dict) else getattr(resp, "models", [])
        for m in models_list:
            name = m.get("model") or m.get("name") if isinstance(m, dict) else (getattr(m, "model", None) or getattr(m, "name", None))
            size_bytes = m.get("size", 0) if isinstance(m, dict) else getattr(m, "size", 0)
            if name:
                gb = round(size_bytes / (1024 ** 3), 1) if size_bytes else 0
                installed.append({
                    "name": str(name),
                    "size_str": f"{gb} GB" if gb > 0 else "설치됨"
                })
    except Exception as e:
        logger.warning(f"Failed to query Ollama models list: {e}")
    return installed


@router.get("/settings")
async def get_system_settings_endpoint():
    """Returns current LLM & Whisper settings and available options for Admin UI select boxes."""
    current = get_runtime_settings(mask_keys=True)
    installed_list = _get_installed_ollama_models()
    installed_names = {m["name"] for m in installed_list}

    # Merge recommended models with installed status
    merged_ollama_models = []
    seen_names = set()

    for rec in RECOMMENDED_OLLAMA_MODELS:
        is_inst = rec["name"] in installed_names
        merged_ollama_models.append({
            **rec,
            "installed": is_inst
        })
        seen_names.add(rec["name"])

    # Also include any other custom models installed in local Ollama
    for inst in installed_list:
        if inst["name"] not in seen_names:
            merged_ollama_models.append({
                "name": inst["name"],
                "label": f"{inst['name']} (로컬 설치 모델 - {inst['size_str']})",
                "size_str": inst["size_str"],
                "desc": "현재 로컬 Ollama 서버에 설치되어 있는 모델",
                "recommended": False,
                "installed": True
            })
            seen_names.add(inst["name"])

    cloud_models = {
        "openai": ["gpt-4o", "gpt-4o-mini", "o3-mini", "gpt-4-turbo"],
        "anthropic": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"],
        "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-pro", "gemini-1.5-flash"],
    }

    return {
        "current": current,
        "db_type": "sqlite" if db.is_sqlite_db() else "postgres",
        "connected_db": db._connected_db_name or ("SQLite" if db.is_sqlite_db() else "PostgreSQL"),
        "ollama_models": merged_ollama_models,
        "installed_ollama_models": [m["name"] for m in installed_list],
        "cloud_models": cloud_models,
        "whisper_models": WHISPER_MODEL_OPTIONS,
        "whisper_devices": WHISPER_DEVICE_OPTIONS,
        "whisper_compute_types": WHISPER_COMPUTE_OPTIONS,
        "ollama_host": OLLAMA_HOST
    }


@router.post("/settings")
async def update_system_settings_endpoint(
    payload: SystemSettingsUpdateRequest,
    background_tasks: BackgroundTasks
):
    """Updates and persists LLM & Whisper configuration immediately, optionally re-queuing completed tasks."""
    requeue_flag = payload.requeue_completed if payload.requeue_completed is not None else True
    updates = payload.model_dump(exclude_none=True, exclude={"requeue_completed"})
    updated = update_runtime_settings(updates)
    logger.info(f"System settings updated by user: {updated} (requeue_completed={requeue_flag})")

    requeue_info = None
    msg = "설정이 저장되어 즉시 적용되었습니다."
    if requeue_flag:
        try:
            requeue_info = execute_requeue_completed_tasks(reset_processing=False, background_tasks=background_tasks)
            rq_cnt = requeue_info.get("requeued_count", 0)
            if rq_cnt > 0:
                msg = f"설정이 저장 및 적용되었으며, 기존 완료된 작업 {rq_cnt}건이 새 설정 기준으로 대기열에 다시 등록되었습니다."
        except Exception as e:
            logger.warning(f"Failed to auto-requeue completed tasks on settings update: {e}")

    # Return masked view of updated settings
    masked_current = get_runtime_settings(mask_keys=True)
    return {
        "message": msg,
        "current": masked_current,
        "requeue": requeue_info
    }


@router.post("/settings/test-cloud-llm")
async def test_cloud_llm_endpoint(payload: CloudLLMTestRequest):
    """Tests connectivity with designated provider (OpenAI, Anthropic, Gemini, Ollama) without blocking event loop."""
    from app.services.llm_provider import test_provider_connectivity
    res = await run_in_threadpool(
        test_provider_connectivity,
        provider=payload.provider,
        api_key=payload.api_key,
        model=payload.model
    )
    return res


@router.post("/settings/pull-model")
async def pull_ollama_model_endpoint(payload: PullModelRequest):
    """Downloads/pulls a model from Ollama registry in threadpool to prevent freezing FastAPI event loop."""
    model_name = payload.model_name.strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="모델 이름을 입력해 주세요.")
    try:
        logger.info(f"Pulling Ollama model: {model_name}...")
        client = ollama.Client(host=OLLAMA_HOST)
        await run_in_threadpool(client.pull, model_name)
        logger.info(f"Successfully pulled Ollama model: {model_name}")
        return {
            "success": True,
            "model_name": model_name,
            "message": f"'{model_name}' 모델 다운로드 및 설치가 완료되었습니다."
        }
    except Exception as e:
        logger.error(f"Failed to pull Ollama model '{model_name}': {e}")
        raise HTTPException(status_code=500, detail=f"모델 다운로드 실패: {str(e)}")


# ==============================================================================
# Proper Noun Dictionary Endpoints (고유명사 사전 API)
# ==============================================================================

@router.get("/dictionary")
async def get_dictionary_endpoint(
    page: int = Query(1, ge=1, description="페이지 번호 (기본 1)"),
    size: int = Query(50, ge=1, le=200, description="페이지당 건수 (기본 50건)"),
    query: Optional[str] = Query(None, description="원문 또는 번역어 검색어")
):
    """고유명사 사전 50건 단위 페이징 목록 조회"""
    return db.get_dictionary_entries(page=page, size=size, query=query)


@router.post("/dictionary")
async def add_dictionary_entry_endpoint(payload: DictionaryEntryCreate):
    """고유명사 사전 신규 단어 등록 (원문 중복 시 업데이트)"""
    try:
        entry = db.add_dictionary_entry(
            source_word=payload.source_word,
            target_word=payload.target_word,
            notes=payload.notes
        )
        return {"message": "고유명사가 성공적으로 등록되었습니다.", "entry": entry}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error adding dictionary entry: {e}")
        raise HTTPException(status_code=500, detail=f"고유명사 등록 오류: {str(e)}")


@router.put("/dictionary/{entry_id}")
async def update_dictionary_entry_endpoint(entry_id: int, payload: DictionaryEntryUpdate):
    """고유명사 사전 단어 수정"""
    try:
        updated = db.update_dictionary_entry(
            entry_id=entry_id,
            source_word=payload.source_word,
            target_word=payload.target_word,
            notes=payload.notes
        )
        if not updated:
            raise HTTPException(status_code=404, detail="해당 고유명사 항목을 찾을 수 없습니다.")
        return {"message": "고유명사가 수정되었습니다.", "entry": updated}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error updating dictionary entry: {e}")
        raise HTTPException(status_code=500, detail=f"고유명사 수정 오류: {str(e)}")


@router.delete("/dictionary/{entry_id}")
async def delete_dictionary_entry_endpoint(entry_id: int):
    """고유명사 항목 단건 삭제"""
    deleted = db.delete_dictionary_entry(entry_id)
    return {"message": "고유명사가 삭제되었습니다.", "success": deleted}


@router.post("/dictionary/batch-delete")
async def batch_delete_dictionary_endpoint(payload: DictionaryBatchDelete):
    """고유명사 항목 일괄 다중 삭제"""
    deleted_count = db.batch_delete_dictionary_entries(payload.ids)
    return {"message": f"{deleted_count}건의 고유명사가 삭제되었습니다.", "deleted_count": deleted_count}


