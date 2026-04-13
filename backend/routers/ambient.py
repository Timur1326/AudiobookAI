import json
import os
import time
from pathlib import Path

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import AmbientScene, Book, Chapter, Paragraph, ParagraphTimestamp, Scene

router = APIRouter()

STORAGE_DIR   = Path("storage/uploads")
AMBIENT_CACHE = Path("storage/ambient_cache")
FREESOUND_URL = "https://freesound.org/apiv2"


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)



def get_scene_ranges_from_db(db, db_chapter, engine: str) -> list[dict]:
    """Return [{start, end, preview}] for each scene using data from the database."""
    scenes = (db.query(Scene)
                .filter(Scene.chapter_id == db_chapter.id)
                .order_by(Scene.scene_index)
                .all())

    ranges = []
    for scene in scenes:
        paras = (db.query(Paragraph)
                   .filter(Paragraph.scene_id == scene.id)
                   .order_by(Paragraph.index)
                   .all())

        para_ids = [p.id for p in paras]
        ts_rows  = (db.query(ParagraphTimestamp)
                      .filter(ParagraphTimestamp.paragraph_id.in_(para_ids),
                              ParagraphTimestamp.engine == engine)
                      .all())

        start   = min(t.start for t in ts_rows) if ts_rows else None
        end     = max(t.end   for t in ts_rows) if ts_rows else None
        preview = scene.preview or ""

        ranges.append({"start": start, "end": end, "preview": preview})

    return ranges


def freesound_search(query: str, api_key: str) -> dict | None:
    try:
        r = requests.get(
            f"{FREESOUND_URL}/search/text/",
            params={
                "query":     query,
                "fields":    "id,name,duration,previews",
                "filter":    "duration:[20 TO *]",
                "sort":      "rating_desc",
                "page_size": 5,
                "token":     api_key,
            },
            timeout=10,
        )
        results = r.json().get("results", [])
        return results[0] if results else None
    except Exception:
        return None


def freesound_download(sound: dict, api_key: str, dest: Path) -> bool:
    if dest.exists():
        return True
    url = sound["previews"].get("preview-hq-mp3") or sound["previews"].get("preview-lq-mp3")
    if not url:
        return False
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return False
        AMBIENT_CACHE.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(r.content)
        return True
    except Exception:
        return False


def generate_queries_llm(scenes_text: list[str]) -> list[list[str]]:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    numbered = "\n\n".join(
        f"Scene {i+1}:\n{text[:400]}" for i, text in enumerate(scenes_text)
    )
    prompt = (
        "You are a sound designer for an audiobook. "
        "For each scene below, generate 3 Freesound.org search queries "
        "for ambient background sound — from most specific to most general.\n"
        "Rules:\n"
        "- Focus on SETTING and MOOD, not the plot\n"
        "- Use short keyword phrases (2-4 words)\n"
        "- Third query must always return results (use generic: nature/indoor/outdoor)\n"
        "- Return ONLY valid JSON array: [[q1,q2,q3], [q1,q2,q3], ...]\n\n"
        f"{numbered}"
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def _set_ambient_status(book: str, chapter_id: int, engine: str, status: str, error: str = ""):
    """Write status to a small JSON file (lightweight, no DB write needed for status)."""
    status_path = STORAGE_DIR / book / "audio" / engine / f"chapter_{chapter_id:02d}_ambient_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    with open(status_path, "w") as f:
        json.dump({"status": status, "error": error}, f)


def _generate_ambient_bg(book: str, chapter_id: int, engine: str):
    """Background task: generate ambient config and save to database."""
    _set_ambient_status(book, chapter_id, engine, "running")

    try:
        from backend.database import SessionLocal
        db = SessionLocal()
        try:
            db_book = db.query(Book).filter(Book.slug == book).first()
            if not db_book:
                _set_ambient_status(book, chapter_id, engine, "error", "Book not found in DB")
                return

            db_chapter = db.query(Chapter).filter(
                Chapter.book_id == db_book.id,
                Chapter.chapter_id == chapter_id,
            ).first()
            if not db_chapter:
                _set_ambient_status(book, chapter_id, engine, "error", "Chapter not found in DB")
                return

            # Get scene ranges from DB — no JSON files needed
            scene_ranges = get_scene_ranges_from_db(db, db_chapter, engine)
            if not scene_ranges:
                _set_ambient_status(book, chapter_id, engine, "error",
                                    "No scenes found — run scene detection pipeline step first")
                return

            scenes_text       = [r["preview"] for r in scene_ranges]
            queries_per_scene = generate_queries_llm(scenes_text)
            freesound_key     = os.environ.get("FREESOUND_API_KEY", "")

            # Remove old ambient scenes for this chapter+engine
            db.query(AmbientScene).filter(
                AmbientScene.chapter_id == db_chapter.id,
                AmbientScene.engine == engine,
            ).delete()

            for i, (queries, rng) in enumerate(zip(queries_per_scene, scene_ranges)):
                sound_url = None

                if freesound_key:
                    for q in queries:
                        result = freesound_search(q, freesound_key)
                        if result:
                            dest = AMBIENT_CACHE / f"{result['id']}.mp3"
                            if freesound_download(result, freesound_key, dest):
                                sound_url = f"/ambient-files/{result['id']}.mp3"
                                break
                        time.sleep(0.3)

                db.add(AmbientScene(
                    chapter_id=db_chapter.id,
                    engine=engine,
                    scene_index=i,
                    start=rng["start"],
                    end=rng["end"],
                    sound_url=sound_url,
                    queries=json.dumps(queries),
                ))

            db.commit()
        finally:
            db.close()

        _set_ambient_status(book, chapter_id, engine, "done")

    except Exception as e:
        _set_ambient_status(book, chapter_id, engine, "error", str(e))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{book}/chapters/{chapter_id}/ambient/generate")
def generate_ambient(book: str, chapter_id: int, background_tasks: BackgroundTasks,
                     engine: str = "elevenlabs"):
    """Start ambient sound generation for a chapter (runs in background)."""
    status_path = STORAGE_DIR / book / "audio" / engine / f"chapter_{chapter_id:02d}_ambient_status.json"

    if status_path.exists():
        status = load_json(status_path).get("status")
        if status == "running":
            raise HTTPException(409, "Ambient generation already running")

    background_tasks.add_task(_generate_ambient_bg, book, chapter_id, engine)
    return {"ok": True, "status": "started"}


@router.get("/{book}/chapters/{chapter_id}/ambient")
def get_ambient(book: str, chapter_id: int, engine: str = "elevenlabs",
                db: Session = Depends(get_db)):
    """Return ambient config + generation status for a chapter."""
    # Check status file
    status_path = STORAGE_DIR / book / "audio" / engine / f"chapter_{chapter_id:02d}_ambient_status.json"
    status = "none"
    if status_path.exists():
        status = load_json(status_path).get("status", "none")

    # Load scenes from DB
    db_book = db.query(Book).filter(Book.slug == book).first()
    if not db_book:
        return {"status": status, "scenes": []}

    db_chapter = db.query(Chapter).filter(
        Chapter.book_id == db_book.id,
        Chapter.chapter_id == chapter_id,
    ).first()
    if not db_chapter:
        return {"status": status, "scenes": []}

    scenes = (db.query(AmbientScene)
                .filter(AmbientScene.chapter_id == db_chapter.id,
                        AmbientScene.engine == engine)
                .order_by(AmbientScene.scene_index)
                .all())

    if scenes:
        return {
            "status": "done",
            "scenes": [
                {
                    "scene_index": s.scene_index,
                    "start":       s.start,
                    "end":         s.end,
                    "sound_url":   s.sound_url,
                    "queries":     json.loads(s.queries) if s.queries else [],
                }
                for s in scenes
            ],
        }

    return {"status": status, "scenes": []}


@router.get("/ambient-files/{filename}")
def serve_ambient_file(filename: str):
    """Serve a cached ambient sound file."""
    path = AMBIENT_CACHE / filename
    if not path.exists():
        raise HTTPException(404, "Ambient file not found")
    return FileResponse(str(path), media_type="audio/mpeg")