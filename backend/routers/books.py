"""Books router: upload, list, inspect books and serve chapter content."""

import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from backend.auth import get_current_user, get_owned_book
from backend.database import get_db
from backend.models import Book, Chapter, Paragraph, ParagraphTimestamp, PipelineStep, StepStatus, User

router = APIRouter()

STORAGE_DIR = Path("storage/uploads")
TOTAL_STEPS = 7


# ── GET /books ────────────────────────────────────────────────────────────────

@router.get("/")
def list_books(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """List books belonging to the current user."""
    books = (db.query(Book)
               .filter(Book.user_id == current_user.id)
               .order_by(Book.created_at.desc())
               .all())

    result = []
    for book in books:
        steps = {s.step: s.status for s in book.steps}
        done_count = sum(1 for s in steps.values() if s == StepStatus.done)
        result.append({
            "slug":       book.slug,
            "title":      book.title,
            "author":     book.author,
            "created_at": book.created_at.isoformat(),
            "progress":   {"done": done_count, "total": TOTAL_STEPS},
            "steps":      {str(k): v for k, v in steps.items()},
        })

    return {"books": result}


# ── POST /books/upload ────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_book(file: UploadFile = File(...), db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    """Upload an EPUB file, parse it, and register in DB."""
    if not file.filename.endswith(".epub"):
        raise HTTPException(status_code=400, detail="Only EPUB files are supported")

    slug = Path(file.filename).stem.lower().replace(" ", "_")

    # Check for duplicate
    existing = db.query(Book).filter(Book.slug == slug).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Book '{slug}' already exists")

    book_dir = STORAGE_DIR / slug
    book_dir.mkdir(parents=True, exist_ok=True)

    epub_path = book_dir / file.filename
    with open(epub_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Parse EPUB metadata first (lightweight — no paragraph extraction yet)
    from core.parser.epub_parser import parse_epub, parse_epub_to_db
    b = parse_epub(str(epub_path))

    # Save Book to DB
    book = Book(
        slug=slug,
        title=b.title,
        author=getattr(b, "author", ""),
        epub_path=str(epub_path),
        user_id=current_user.id,
    )
    db.add(book)
    db.flush()  # get book.id

    # Create pipeline steps
    for step_num in range(1, TOTAL_STEPS + 1):
        db.add(PipelineStep(book_id=book.id, step=step_num, status=StepStatus.pending))
    db.flush()

    # Parse EPUB and write chapters + paragraphs directly to DB
    total_paragraphs = parse_epub_to_db(str(epub_path), book.id, db)

    # Mark step 1 as done
    step1 = db.query(PipelineStep).filter(
        PipelineStep.book_id == book.id, PipelineStep.step == 1
    ).first()
    if step1:
        step1.status = StepStatus.done
        step1.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(book)

    chapter_count = db.query(Chapter).filter(Chapter.book_id == book.id).count()

    return {
        "slug":       slug,
        "title":      book.title,
        "chapters":   chapter_count,
        "paragraphs": total_paragraphs,
    }


# ── GET /books/{book} ─────────────────────────────────────────────────────────

@router.get("/{book}")
def get_book(book: str, db: Session = Depends(get_db), db_book: Book = Depends(get_owned_book)):
    """Get book metadata, chapter list, and pipeline status."""
    steps = [
        {
            "step":       s.step,
            "name":       s.name,
            "status":     s.status,
            "updated_at": s.updated_at.isoformat(),
            "error_msg":  s.error_msg,
        }
        for s in sorted(db_book.steps, key=lambda x: x.step)
    ]

    chapters = [
        {
            "id":           ch.chapter_id,
            "index":        ch.chapter_index,
            "title":        ch.title,
            "synth_status": ch.synth_status,
            "synth_engine": ch.synth_engine,
            "audio_path":   ch.audio_path,
        }
        for ch in db_book.chapters
    ]

    return {
        "slug":       db_book.slug,
        "title":      db_book.title,
        "author":     db_book.author,
        "created_at": db_book.created_at.isoformat(),
        "steps":      steps,
        "chapters":   chapters,
    }


# ── GET /books/{book}/cover ───────────────────────────────────────────────────

@router.get("/{book}/cover")
def get_book_cover(book: str, db_book: Book = Depends(get_owned_book)):
    """Return the cover image for a book. Extracts it on first request if missing."""
    from fastapi.responses import FileResponse
    book_dir = STORAGE_DIR / book

    # Return existing cover
    for ext in ("jpg", "jpeg", "png", "webp"):
        cover = book_dir / f"cover.{ext}"
        if cover.exists():
            return FileResponse(str(cover))

    # Try to extract from epub
    if db_book.epub_path:
        try:
            from core.parser.epub_parser import extract_cover
            result = extract_cover(db_book.epub_path, str(book_dir))
            if result:
                return FileResponse(result)
        except Exception:
            pass

    raise HTTPException(status_code=404, detail="No cover image found")


# ── DELETE /books/{book} ──────────────────────────────────────────────────────

@router.delete("/{book}")
def delete_book(book: str, db: Session = Depends(get_db), db_book: Book = Depends(get_owned_book)):
    """Delete a book and all its files."""
    book_dir = STORAGE_DIR / book
    if book_dir.exists():
        shutil.rmtree(book_dir)

    db.delete(db_book)
    db.commit()

    return {"ok": True, "deleted": book}


# ── GET /books/{book}/chapters/{chapter_id}/reader ────────────────────────────

@router.get("/{book}/chapters/{chapter_id}/reader")
def get_chapter_reader(book: str, chapter_id: int, engine: str = "elevenlabs",
                       db: Session = Depends(get_db), db_book: Book = Depends(get_owned_book)):
    """Return paragraphs with timestamps from the database."""
    db_chapter = db.query(Chapter).filter(
        Chapter.book_id == db_book.id,
        Chapter.chapter_id == chapter_id,
    ).first()
    if not db_chapter:
        raise HTTPException(404, f"Chapter {chapter_id} not found")

    db_paras = (db.query(Paragraph)
                  .filter(Paragraph.chapter_id == db_chapter.id)
                  .order_by(Paragraph.index)
                  .all())
    if not db_paras:
        raise HTTPException(404, f"No paragraphs found for chapter {chapter_id}")

    para_ids = [p.id for p in db_paras]
    ts_rows = (db.query(ParagraphTimestamp)
                 .filter(ParagraphTimestamp.paragraph_id.in_(para_ids),
                         ParagraphTimestamp.engine == engine)
                 .all())
    ts_by_para_id = {t.paragraph_id: t for t in ts_rows}

    paras = []
    for p in db_paras:
        ts = ts_by_para_id.get(p.id)
        paras.append({
            "index":   p.index,
            "text":    p.text,
            "type":    p.type,
            "speaker": p.speaker,
            "start":   ts.start if ts else None,
            "end":     ts.end   if ts else None,
        })

    return {"id": chapter_id, "title": db_chapter.title, "paragraphs": paras}