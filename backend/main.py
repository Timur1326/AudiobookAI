"""
FastAPI application entry point.

Start the server:
    uvicorn backend.main:app --reload
"""

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.database import Base, engine
from backend.routers import books, voices, synthesis, pipeline, gutenberg, ambient, auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all DB tables on startup (no-op if they already exist)
    Base.metadata.create_all(bind=engine)

    # Reset any pipeline steps that were left in "running" state by a previous crash
    from backend.database import SessionLocal
    from backend.models import PipelineStep, Chapter, StepStatus
    db = SessionLocal()
    try:
        db.query(PipelineStep).filter(PipelineStep.status == StepStatus.running)\
            .update({"status": StepStatus.error, "error_msg": "Interrupted by server restart"})
        db.query(Chapter).filter(Chapter.synth_status == StepStatus.running)\
            .update({"synth_status": StepStatus.error})
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
    yield


app = FastAPI(title="Audiobook API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# All book-related routers share the /books prefix
app.include_router(auth.router)
app.include_router(books.router,       prefix="/books",       tags=["books"])
app.include_router(voices.router,      prefix="/books",       tags=["voices"])
app.include_router(synthesis.router,   prefix="/books",       tags=["synthesis"])
app.include_router(pipeline.router,    prefix="/books",       tags=["pipeline"])
app.include_router(gutenberg.router,   prefix="/books",       tags=["gutenberg"])
app.include_router(ambient.router,     prefix="/books",       tags=["ambient"])

@app.get("/ambient-files/{filename}")
def serve_ambient(filename: str):
    """Serve a generated ambient sound file from the local cache."""
    p = Path("storage/ambient_cache") / filename
    if not p.exists():
        raise HTTPException(404)
    media_type = "audio/wav" if filename.endswith(".wav") else "audio/mpeg"
    return FileResponse(str(p), media_type=media_type)



@app.get("/")
def root():
    return {"status": "ok", "message": "Audiobook API"}