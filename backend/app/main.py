import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api.routes import router as api_router
from app.database import init_db

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()

        import threading
        # Background sync of existing SRT files from media scan directories into completed_tasks
        def _bg_sync_disk():
            try:
                from app.database import sync_disk_srt_to_completed_tasks
                sync_disk_srt_to_completed_tasks()
            except Exception as sync_err:
                logging.warning(f"Background disk SRT sync failed: {sync_err}")

        threading.Thread(target=_bg_sync_disk, daemon=True).start()

        # Auto-resume any interrupted PROCESSING tasks in background thread
        from sqlalchemy import text
        from app.database import get_engine
        from app.api.routes import run_pipeline, tasks, TaskStatus
        
        with get_engine().connect() as conn:
            interrupted = conn.execute(
                text("SELECT task_id, filename, video_path, stage, progress FROM transm_tasks WHERE status = 'PROCESSING'")
            ).mappings().all()
            
            from app.api.routes import run_translation_pipeline, load_segments_from_task

            for row in interrupted:
                t_id = row["task_id"]
                v_path_str = row["video_path"]
                fname = row["filename"]
                stage = row["stage"] or ""
                prog = row["progress"] or 10

                if fname.endswith(".srt") or "번역" in stage:
                    logging.info(f"Auto-resuming interrupted translation task {t_id} ({fname}) on startup...")
                    _, segments = load_segments_from_task(t_id)
                    if segments:
                        if t_id not in tasks:
                            tasks[t_id] = TaskStatus(
                                task_id=t_id,
                                filename=fname,
                                status="PROCESSING",
                                stage=stage or "자막 번역 자동 복구 및 이어하기 중...",
                                progress=prog,
                                video_url=f"/api/video/{t_id}"
                            )
                        t_lang = "ko"
                        if "_" in fname:
                            stem_suffix = Path(fname).stem.split("_")[-1]
                            if len(stem_suffix) == 2:
                                t_lang = stem_suffix
                        threading.Thread(
                            target=run_translation_pipeline,
                            args=(t_id, segments, fname, t_lang),
                            daemon=True
                        ).start()
                    else:
                        logging.warning(f"Could not find source segments to auto-resume task {t_id}. Marking as FAILED.")
                        from app.database import upsert_task
                        upsert_task(
                            task_id=t_id,
                            filename=fname,
                            status="FAILED",
                            stage="작업 중단 후 원본 세그먼트를 찾을 수 없어 종료되었습니다.",
                            progress=prog,
                            error="서버 재시작 후 원본 세그먼트 부재로 인한 중단"
                        )
                elif v_path_str and Path(v_path_str).exists():
                    logging.info(f"Auto-resuming interrupted video task {t_id} ({fname}) on startup...")
                    if t_id not in tasks:
                        tasks[t_id] = TaskStatus(
                            task_id=t_id,
                            filename=fname,
                            status="PROCESSING",
                            stage="작업 자동 복구 및 이어하기 중...",
                            progress=80,
                            video_url=f"/api/video/{t_id}"
                        )
                    threading.Thread(
                        target=run_pipeline,
                        args=(t_id, Path(v_path_str), fname),
                        daemon=True
                    ).start()

            if not interrupted:
                from app.api.routes import auto_start_next_waiting_item
                auto_start_next_waiting_item()
    except Exception as e:
        logging.error(f"Failed to initialize PostgreSQL database or auto-resume: {e}")
    yield

app = FastAPI(
    title="TransM - AI Subtitle Generator",
    description="Video to refined SRT subtitle generator using faster-whisper and Ollama gemma4:12b",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for local development (Vite frontend on 5173 or 3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(api_router)

@app.get("/healthz")
async def health_check():
    return {"status": "ok", "service": "TransM Subtitle API"}

# Serve frontend build from FastAPI for seamless single-port access (http://localhost:8000)
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api") or full_path in ["healthz", "docs", "openapi.json", "redoc"]:
            return None
        file_path = FRONTEND_DIST / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIST / "index.html")
