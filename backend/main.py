from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import Base, engine
from backend.routers import books, attribution, voices, synthesis, pipeline, gutenberg, ambient, auth

# Create all tables on startup
Base.metadata.create_all(bind=engine)

# Reset stale "running" states left from previous server runs
def _reset_stale_running():
    from backend.database import SessionLocal
    from backend.models import PipelineStep, Chapter, StepStatus
    db = SessionLocal()
    try:
        db.query(PipelineStep).filter(PipelineStep.status == StepStatus.running)\
            .update({"status": StepStatus.error, "error_msg": "Interrupted by server restart"})
        db.query(Chapter).filter(Chapter.synth_status == StepStatus.running)\
            .update({"synth_status": StepStatus.error})
        db.commit()
    finally:
        db.close()

_reset_stale_running()

app = FastAPI(title="Audiobook API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(books.router,       prefix="/books",       tags=["books"])
app.include_router(attribution.router, prefix="/books",       tags=["attribution"])
app.include_router(voices.router,      prefix="/books",       tags=["voices"])
app.include_router(synthesis.router,   prefix="/books",       tags=["synthesis"])
app.include_router(pipeline.router,    prefix="/books",       tags=["pipeline"])
app.include_router(gutenberg.router,   prefix="/books",       tags=["gutenberg"])
app.include_router(ambient.router,     prefix="/books",       tags=["ambient"])

# Ambient file serving (no /books prefix)
from fastapi.responses import FileResponse as _FR
from pathlib import Path as _Path
@app.get("/ambient-files/{filename}")
def serve_ambient(filename: str):
    p = _Path("storage/ambient_cache") / filename
    if not p.exists():
        from fastapi import HTTPException
        raise HTTPException(404)
    return _FR(str(p), media_type="audio/mpeg")


@app.get("/tasks/{task_id}")
def get_task_status(task_id: str):
    """Get status of a Celery background task."""
    try:
        from celery.result import AsyncResult
        from backend.worker import celery_app
        result = AsyncResult(task_id, app=celery_app)
        return {
            "task_id": task_id,
            "status":  result.state,        # PENDING / STARTED / SUCCESS / FAILURE / RETRY
            "result":  result.result if result.ready() else None,
        }
    except Exception:
        return {"task_id": task_id, "status": "UNKNOWN", "result": None}


@app.get("/")
def root():
    return {"status": "ok", "message": "Audiobook API"}