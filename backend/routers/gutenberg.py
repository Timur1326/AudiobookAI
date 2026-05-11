"""
Project Gutenberg search and import via OPDS catalog.
"""

import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_current_user_optional
from backend.database import get_db
from backend.models import Book, Chapter, PipelineStep, StepStatus, User

router = APIRouter()

GUTENBERG_OPDS = "https://www.gutenberg.org/ebooks/search/"
STORAGE_DIR    = Path("storage/uploads")

_NS = {
    "atom":   "http://www.w3.org/2005/Atom",
    "dc":     "http://purl.org/dc/terms/",
    "os":     "http://a9.com/-/spec/opensearch/1.1/",
}


def _text(el, tag: str) -> str:
    """Return stripped text content of a child XML element, or empty string if absent."""
    child = el.find(tag, _NS)
    return child.text.strip() if child is not None and child.text else ""


def _resolve_epub_url(gutenberg_id: int) -> str | None:
    """
    Fetch the per-book OPDS page and return the best epub URL.
    Prefers epub+zip without images (smaller).
    Returns None if no epub is available (e.g. audio-only books).
    """
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(f"https://www.gutenberg.org/ebooks/{gutenberg_id}.opds")
            resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        return None

    noimages = None
    images   = None
    for el in root.iter():
        if not el.tag.endswith("}link") and el.tag != "link":
            continue
        if el.get("type") != "application/epub+zip":
            continue
        if el.get("rel") != "http://opds-spec.org/acquisition":
            continue
        href = el.get("href", "")
        if "noimages" in href:
            noimages = href
        else:
            images = images or href

    return noimages or images or None


@router.get("/gutenberg/search")
def search_gutenberg(q: str, page: int = 1):
    """Search Project Gutenberg via OPDS catalog."""
    if not q.strip():
        return {"results": [], "count": 0}

    params = {"query": q.strip(), "format": "opds"}
    if page > 1:
        params["start_index"] = (page - 1) * 25

    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            resp = client.get(GUTENBERG_OPDS, params=params)
            resp.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Gutenberg search timeout")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Gutenberg API error: {e}")

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        raise HTTPException(status_code=502, detail=f"Invalid XML from Gutenberg: {e}")

    results = []
    for entry in root.findall("atom:entry", _NS):
        title = _text(entry, "atom:title")
        if not title:
            continue

        # ID: "https://www.gutenberg.org/ebooks/11.opds" — skip navigation entries
        id_text = _text(entry, "atom:id")
        m = re.search(r"/ebooks/(\d+)(?:\.opds)?$", id_text.rstrip())
        if not m:
            continue
        gutenberg_id = int(m.group(1))

        # Author is in <content> in search results (not <author>/<name>)
        content_el = entry.find("atom:content", _NS)
        author = content_el.text.strip() if content_el is not None and content_el.text else "Unknown"

        # Epub URL: construct directly (reliable, works for all books)
        epub_url = f"https://www.gutenberg.org/ebooks/{gutenberg_id}.epub.noimages"

        # Subjects
        subjects = [
            s.text.strip()
            for s in entry.findall("dc:subject", _NS)
            if s.text
        ][:3]

        # Language
        lang_el  = entry.find("dc:language", _NS)
        lang     = lang_el.text.strip() if lang_el is not None and lang_el.text else ""

        results.append({
            "id":        gutenberg_id,
            "title":     title,
            "author":    author,
            "epub_url":  epub_url,
            "subjects":  subjects,
            "languages": [lang] if lang else [],
        })

    # OpenSearch total count
    total_el = root.find("os:totalResults", _NS)
    count    = int(total_el.text) if total_el is not None and total_el.text else len(results)

    next_link = None
    for link in root.findall("atom:link", _NS):
        if link.get("rel") == "next":
            next_link = link.get("href")
            break

    return {
        "results": results,
        "count":   count,
        "next":    next_link,
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

    epub_url = _resolve_epub_url(body.gutenberg_id)
    if not epub_url:
        shutil.rmtree(book_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail="No EPUB available for this book")

    # Download epub
    epub_path = book_dir / f"{slug}.epub"
    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            resp = client.get(epub_url)
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