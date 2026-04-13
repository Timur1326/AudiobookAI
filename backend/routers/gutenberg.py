"""
Project Gutenberg search and import via Gutendex API.
"""

import shutil
import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_current_user_optional
from backend.database import get_db
from backend.models import Book, Chapter, PipelineStep, StepStatus, User

router = APIRouter()

GUTENDEX_URL = "https://gutendex.com/books"
STORAGE_DIR  = Path("storage/uploads")


@router.get("/gutenberg/search")
def search_gutenberg(q: str, page: int = 1):
    """Search Project Gutenberg via Gutendex API."""
    if not q.strip():
        return {"results": [], "count": 0}

    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(GUTENDEX_URL, params={"search": q, "page": page})
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Gutenberg API timeout")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Gutenberg API error: {e}")

    results = []
    for book in data.get("results", []):
        authors = book.get("authors", [])
        author  = authors[0]["name"] if authors else "Unknown"

        # Find best epub URL
        formats  = book.get("formats", {})
        epub_url = (
            formats.get("application/epub+zip") or
            formats.get("application/epub")
        )
        if not epub_url:
            continue

        results.append({
            "id":       book["id"],
            "title":    book.get("title", "Unknown"),
            "author":   author,
            "epub_url": epub_url,
            "subjects": book.get("subjects", [])[:3],
            "languages": book.get("languages", []),
        })

    return {
        "results": results,
        "count":   data.get("count", 0),
        "next":    data.get("next"),
    }


class ImportRequest(BaseModel):
    gutenberg_id: int
    title:        str
    author:       str
    epub_url:     str


@router.post("/gutenberg/import")
def import_gutenberg(body: ImportRequest, db: Session = Depends(get_db),
                     current_user: User | None = Depends(get_current_user_optional)):
    """Download EPUB from Gutenberg and import it as a new book."""
    # Build slug from gutenberg id + title
    safe_title = "".join(c if c.isalnum() or c in " _-" else "" for c in body.title.lower())
    safe_title = safe_title.strip().replace(" ", "_")[:40]
    slug = f"gutenberg_{body.gutenberg_id}_{safe_title}"

    # Check duplicate
    if db.query(Book).filter(Book.slug == slug).first():
        raise HTTPException(status_code=409, detail=f"Book '{slug}' already imported")

    book_dir = STORAGE_DIR / slug
    book_dir.mkdir(parents=True, exist_ok=True)

    # Download epub
    epub_path = book_dir / f"{slug}.epub"
    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            resp = client.get(body.epub_url)
            resp.raise_for_status()
            epub_path.write_bytes(resp.content)
    except httpx.HTTPError as e:
        shutil.rmtree(book_dir, ignore_errors=True)
        raise HTTPException(status_code=502, detail=f"Failed to download EPUB: {e}")

    TOTAL_STEPS = 7

    # Save book to DB first so we have book.id for parse_epub_to_db
    book = Book(
        slug=slug,
        title=body.title,
        author=body.author,
        epub_path=str(epub_path),
        user_id=current_user.id if current_user else None,
    )
    db.add(book)
    db.flush()

    for step_num in range(1, TOTAL_STEPS + 1):
        db.add(PipelineStep(book_id=book.id, step=step_num,
                            status=StepStatus.done if step_num == 1 else StepStatus.pending))
    db.flush()

    # Parse EPUB directly into DB (chapters + paragraphs)
    try:
        from core.parser.epub_parser import parse_epub_to_db
        total_paragraphs = parse_epub_to_db(str(epub_path), book.id, db)
    except Exception as e:
        db.rollback()
        shutil.rmtree(book_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to parse EPUB: {e}")

    db.commit()

    chapter_count = db.query(Chapter).filter(Chapter.book_id == book.id).count()

    return {
        "slug":       slug,
        "title":      body.title,
        "author":     body.author,
        "chapters":   chapter_count,
        "paragraphs": total_paragraphs,
    }