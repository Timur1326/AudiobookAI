"""Synthesis router: trigger TTS synthesis and serve audio files and timestamps."""

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_owned_book
from backend.database import get_db
from backend.models import Book, Chapter, PipelineStep, StepStatus

router = APIRouter()

STORAGE_DIR = Path("storage/uploads")


class SynthesizeRequest(BaseModel):
    chapter_id: int
    engine: str = "elevenlabs"


# ── POST /books/{book}/synthesize ─────────────────────────────────────────────

@router.post("/{book}/synthesize")
def synthesize(book: str, body: SynthesizeRequest, db: Session = Depends(get_db),
               db_book: Book = Depends(get_owned_book)):
    """Synthesize a chapter to MP3 and track status in DB."""
    db_chapter = db.query(Chapter).filter(
        Chapter.book_id == db_book.id,
        Chapter.chapter_id == body.chapter_id,
    ).first()
    if not db_chapter:
        raise HTTPException(status_code=404, detail=f"Chapter {body.chapter_id} not found")

    # Mark as running
    db_chapter.synth_status = StepStatus.running
    db_chapter.synth_engine = body.engine
    db.commit()

    try:
        import core.tts.synthesize_chapter as sc

        result = sc.synthesize_chapter_from_db(
            book_slug=book,
            chapter_id=body.chapter_id,
            engine=body.engine,
            db=db,
        )

        if result is None:
            raise RuntimeError("Synthesis returned None — no segments generated")

        # Mark chapter as done
        db_chapter.synth_status = StepStatus.done
        db_chapter.audio_path = str(result)
        db_chapter.synth_engine = body.engine

        # Mark pipeline step 7 as done if all chapters synthesized
        total = db.query(Chapter).filter(Chapter.book_id == db_book.id).count()
        done  = db.query(Chapter).filter(
            Chapter.book_id == db_book.id,
            Chapter.synth_status == StepStatus.done,
        ).count()
        if done >= total:
            step7 = db.query(PipelineStep).filter(
                PipelineStep.book_id == db_book.id, PipelineStep.step == 7
            ).first()
            if step7:
                step7.status = StepStatus.done
                step7.updated_at = datetime.utcnow()

        db.commit()
        return {"ok": True, "file": str(result)}

    except Exception as exc:
        db_chapter.synth_status = StepStatus.error
        db.commit()
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /books/{book}/chapters/{chapter_id}/timestamps ───────────────────────

@router.get("/{book}/chapters/{chapter_id}/timestamps")
def get_timestamps(book: str, chapter_id: int, engine: str = "elevenlabs",
                   db_book: Book = Depends(get_owned_book)):
    """Return per-paragraph timestamps for a synthesized chapter.
    If timestamps file is missing but segment files exist, rebuilds it on the fly.
    """
    ts_path = STORAGE_DIR / book / "audio" / engine / f"chapter_{chapter_id:02d}_timestamps.json"

    if not ts_path.exists():
        # Try to rebuild from existing segment files
        import core.tts.synthesize_chapter as sc
        result = sc.build_timestamps_from_segments(book, chapter_id, engine)
        if not result:
            raise HTTPException(status_code=404, detail="Timestamps not available — synthesize chapter first")

    with open(ts_path, encoding="utf-8") as f:
        return json.load(f)


# ── GET /books/{book}/audio/{chapter_id} ──────────────────────────────────────

@router.get("/{book}/audio/{chapter_id}")
def get_audio(book: str, chapter_id: int, engine: str = "elevenlabs", db: Session = Depends(get_db),
              db_book: Book = Depends(get_owned_book)):
    """Download synthesized chapter MP3."""
    db_chapter = db.query(Chapter).filter(
        Chapter.book_id == db_book.id,
        Chapter.chapter_id == chapter_id,
    ).first()
    if db_chapter and db_chapter.audio_path:
        path = Path(db_chapter.audio_path)
        if path.exists():
            return FileResponse(str(path), media_type="audio/mpeg", filename=path.name)

    # Fallback: derive path from convention
    path = STORAGE_DIR / book / "audio" / engine / f"chapter_{chapter_id:02d}.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Audio not found: {path}")
    return FileResponse(str(path), media_type="audio/mpeg", filename=path.name)