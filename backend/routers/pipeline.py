import json
import threading
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db
from backend.models import Book, Chapter, Character, PipelineStep, StepStatus

router = APIRouter()

STORAGE_DIR = Path("storage/uploads")


def get_book_or_404(slug: str, db: Session) -> Book:
    book = db.query(Book).filter(Book.slug == slug).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Book '{slug}' not found")
    return book


def set_step_status(book_id: int, step: int, status: StepStatus, error: str = None):
    """Update pipeline step status in a fresh DB session (called from threads)."""
    db = SessionLocal()
    try:
        s = db.query(PipelineStep).filter(
            PipelineStep.book_id == book_id,
            PipelineStep.step == step,
        ).first()
        if s:
            s.status     = status
            s.updated_at = datetime.utcnow()
            s.error_msg  = error
            db.commit()
    finally:
        db.close()


def run_pipeline_steps(book_slug: str, book_id: int, steps: List[int], engine: str):
    """Run pipeline steps sequentially in a background thread."""

    base = STORAGE_DIR / book_slug

    def run_step(step_num: int):
        # Skip checks using DB state instead of JSON files
        check_db = SessionLocal()
        try:
            if step_num == 2:
                # Skip if paragraphs already have type set (not all "narration")
                from backend.models import Paragraph as DBParagraph, Chapter as DBChapter
                dialogue_count = (check_db.query(DBParagraph)
                                  .join(DBChapter)
                                  .filter(DBChapter.book_id == book_id,
                                          DBParagraph.type == "dialogue")
                                  .count())
                if dialogue_count > 0:
                    set_step_status(book_id, step_num, StepStatus.done)
                    return

            elif step_num == 3:
                from backend.models import Scene as DBScene, Chapter as DBChapter
                scene_count = (check_db.query(DBScene)
                               .join(DBChapter)
                               .filter(DBChapter.book_id == book_id)
                               .count())
                if scene_count > 0:
                    set_step_status(book_id, step_num, StepStatus.done)
                    return

            elif step_num == 4:
                # Step 4 = Attribute dialogue (runs first, without character list)
                from backend.models import Paragraph as DBParagraph, Chapter as DBChapter
                total_d = (check_db.query(DBParagraph)
                           .join(DBChapter)
                           .filter(DBChapter.book_id == book_id,
                                   DBParagraph.type == "dialogue")
                           .count())
                attributed = (check_db.query(DBParagraph)
                              .join(DBChapter)
                              .filter(DBChapter.book_id == book_id,
                                      DBParagraph.type == "dialogue",
                                      DBParagraph.speaker.isnot(None))
                              .count())
                if total_d > 0 and attributed / total_d >= 0.8:
                    set_step_status(book_id, step_num, StepStatus.done)
                    return

            elif step_num == 5:
                # Step 5 = Extract characters (runs after attribution)
                from backend.models import Character as DBCharacter
                if check_db.query(DBCharacter).filter(DBCharacter.book_id == book_id).count() > 0:
                    set_step_status(book_id, step_num, StepStatus.done)
                    return

            elif step_num == 6:
                from backend.models import Character as DBCharacter
                voiced = (check_db.query(DBCharacter)
                          .filter(DBCharacter.book_id == book_id,
                                  DBCharacter.voice_id.isnot(None))
                          .count())
                if voiced > 0:
                    set_step_status(book_id, step_num, StepStatus.done)
                    return
        finally:
            check_db.close()

        set_step_status(book_id, step_num, StepStatus.running)
        db = SessionLocal()
        try:
            if step_num == 2:
                from core.nlp.quote_splitter import run_on_db
                run_on_db(book_id=book_id, db=db)

            elif step_num == 3:
                from core.audio.scene_splitter import run_on_db as scene_run_on_db
                scene_run_on_db(book_id=book_id, db=db)

            elif step_num == 4:
                # Attribution first — LLM attributes from context without character list
                from core.nlp.llm_attributor_with_context import run_on_db as attr_run_on_db
                attr_run_on_db(book_id=book_id, db=db)

            elif step_num == 5:
                # Extraction after attribution — uses clean LLM-attributed speakers
                from core.nlp.character_extractor import run_on_db as char_run_on_db
                char_run_on_db(book_id=book_id, db=db)

            elif step_num == 6:
                from core.nlp.voice_assigner import run_on_db as voice_run_on_db
                voice_run_on_db(book_id=book_id, db=db, engine=engine)

            set_step_status(book_id, step_num, StepStatus.done)

        except Exception as e:
            set_step_status(book_id, step_num, StepStatus.error, str(e))
            raise  # stop pipeline on error
        finally:
            db.close()

    for step in sorted(steps):
        run_step(step)


def _import_characters(book_slug: str, book_id: int):
    """Import characters.json into DB after step 5."""
    path = STORAGE_DIR / book_slug / "characters.json"
    if not path.exists():
        return

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    chars_data = raw if isinstance(raw, list) else raw.get("characters", [])

    db = SessionLocal()
    try:
        db.query(Character).filter(Character.book_id == book_id).delete()
        for c in chars_data:
            name = c.get("name") or c.get("character")
            if not name:
                continue
            sample = c.get("sample_text") or c.get("sample")
            if not sample and c.get("dialogues"):
                sample = c["dialogues"][0]
            db.add(Character(
                book_id=book_id,
                name=name,
                aliases=json.dumps(c.get("aliases", []), ensure_ascii=False),
                gender=c.get("gender"),
                age=c.get("age"),
                personality=c.get("personality"),
                accent=c.get("accent"),
                voice_desc=c.get("voice_description") or c.get("voice_desc"),
                sample_text=sample,
            ))
        db.commit()
    finally:
        db.close()


def _sync_voice_map(book_slug: str, book_id: int, engine: str):
    """Sync voice_map_*.json into DB characters after step 6."""
    path = STORAGE_DIR / book_slug / f"voice_map_{engine}.json"
    if not path.exists():
        return

    with open(path, encoding="utf-8") as f:
        voice_map = json.load(f)

    db = SessionLocal()
    try:
        chars = db.query(Character).filter(Character.book_id == book_id).all()
        for char in chars:
            if char.name in voice_map:
                char.voice_id = voice_map[char.name]
                char.engine   = engine
        db.commit()
    finally:
        db.close()


# ── POST /books/{book}/pipeline/run ───────────────────────────────────────────

class PipelineRunRequest(BaseModel):
    steps:  List[int] = [2, 3, 4, 5, 6]
    engine: str       = "elevenlabs"


@router.post("/{book}/pipeline/run")
def run_pipeline(book: str, body: PipelineRunRequest, db: Session = Depends(get_db)):
    """Start pipeline steps in background. Poll GET /books/{book} for status."""
    db_book = get_book_or_404(book, db)

    # Check nothing is already running
    running = db.query(PipelineStep).filter(
        PipelineStep.book_id == db_book.id,
        PipelineStep.status  == StepStatus.running,
    ).first()
    if running:
        raise HTTPException(status_code=409, detail=f"Step {running.step} is already running")

    # Mark requested steps as pending
    for step_num in body.steps:
        s = db.query(PipelineStep).filter(
            PipelineStep.book_id == db_book.id,
            PipelineStep.step    == step_num,
        ).first()
        if s:
            s.status    = StepStatus.pending
            s.error_msg = None
    db.commit()

    # Run in background thread
    thread = threading.Thread(
        target=run_pipeline_steps,
        args=(book, db_book.id, body.steps, body.engine),
        daemon=True,
    )
    thread.start()

    return {"ok": True, "started_steps": body.steps}


# ── POST /books/{book}/pipeline/reset ────────────────────────────────────────

@router.post("/{book}/pipeline/reset")
def reset_pipeline(book: str, db: Session = Depends(get_db)):
    """Reset all pipeline steps to pending (for reprocessing)."""
    db_book = get_book_or_404(book, db)

    steps = db.query(PipelineStep).filter(PipelineStep.book_id == db_book.id).all()
    for s in steps:
        if s.step > 1:  # keep step 1 (parse) as done
            s.status    = StepStatus.pending
            s.error_msg = None
    db.commit()

    return {"ok": True}


# ── POST /books/{book}/synthesize-batch ───────────────────────────────────────

class SynthesizeBatchRequest(BaseModel):
    chapter_ids:     List[int]
    engine:          str = "elevenlabs"
    narrator_style:  str = "standard"


@router.post("/{book}/synthesize-batch")
def synthesize_batch(book: str, body: SynthesizeBatchRequest, db: Session = Depends(get_db)):
    """Synthesize multiple chapters in background."""
    db_book = get_book_or_404(book, db)

    # Reject if any of the requested chapters is already being synthesized
    already_running = db.query(Chapter).filter(
        Chapter.book_id    == db_book.id,
        Chapter.chapter_id.in_(body.chapter_ids),
        Chapter.synth_status == StepStatus.running,
    ).first()
    if already_running:
        raise HTTPException(
            status_code=409,
            detail=f"Chapter {already_running.chapter_id} is already being synthesized",
        )

    # Mark selected chapters as pending
    for ch_id in body.chapter_ids:
        ch = db.query(Chapter).filter(
            Chapter.book_id    == db_book.id,
            Chapter.chapter_id == ch_id,
        ).first()
        if ch:
            ch.synth_status = StepStatus.pending
            ch.synth_engine = body.engine
    db.commit()

    thread = threading.Thread(
        target=_synthesize_chapters_bg,
        args=(book, db_book.id, body.chapter_ids, body.engine, body.narrator_style),
        daemon=True,
    )
    thread.start()

    return {"ok": True, "queued": body.chapter_ids}


def _synthesize_chapters_bg(book_slug: str, book_id: int, chapter_ids: List[int], engine: str, narrator_style: str = "standard"):
    """Synthesize chapters sequentially in background thread."""
    import synthesize_chapter as sc

    for ch_id in chapter_ids:
        db = SessionLocal()
        try:
            db_ch = db.query(Chapter).filter(
                Chapter.book_id    == book_id,
                Chapter.chapter_id == ch_id,
            ).first()
            if not db_ch:
                continue

            # Skip if already running or done (prevents double synthesis)
            if db_ch.synth_status in (StepStatus.running, StepStatus.done):
                continue

            db_ch.synth_status = StepStatus.running
            db_ch.synth_engine = engine
            db.commit()

            result = sc.synthesize_chapter_from_db(
                book_slug=book_slug,
                chapter_id=ch_id,
                engine=engine,
                db=db,
                narrator_style=narrator_style,
            )

            db_ch.synth_status = StepStatus.done if result else StepStatus.error
            db_ch.audio_path   = str(result) if result else None
            db.commit()

        except Exception as e:
            try:
                db_ch.synth_status = StepStatus.error
                db_ch.synth_engine = engine
                db.commit()
            except Exception:
                pass
        finally:
            db.close()