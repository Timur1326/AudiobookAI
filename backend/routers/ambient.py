"""Ambient router: generate and serve per-scene background sound using Freesound."""

import json
import os
import time
from pathlib import Path

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_owned_book, get_owned_scene
from backend.database import get_db
from backend.models import AmbientScene, Book, Chapter, Paragraph, ParagraphTimestamp, Scene

router = APIRouter()

STORAGE_DIR   = Path("storage/uploads")
AMBIENT_CACHE = Path("storage/ambient_cache")
FREESOUND_URL = "https://freesound.org/apiv2"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _ts_start_end(ts_rows) -> tuple[float | None, float | None]:
    """Return (min start, max end) from a list of ParagraphTimestamp rows."""
    starts: list[float] = [t.start for t in ts_rows if t.start is not None]  # type: ignore[misc]
    ends:   list[float] = [t.end   for t in ts_rows if t.end   is not None]  # type: ignore[misc]
    return (min(starts) if starts else None, max(ends) if ends else None)


def _get_scene_ranges_from_db(db, db_chapter, engine: str) -> list[dict]:
    """Return [{scene_id, start, end, preview}] for each scene."""
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

        start, end = _ts_start_end(ts_rows)

        ranges.append({
            "scene_id": scene.id,
            "preview":  scene.preview or "",
            "location": scene.location or "",
            "start":    start,
            "end":      end,
        })

    return ranges


def _freesound_search(query: str, api_key: str) -> dict | None:
    """Search Freesound for a single best match; returns the first result or None."""
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
            timeout=4,
        )
        results = r.json().get("results", [])
        return results[0] if results else None
    except Exception:
        return None


def _freesound_download(sound: dict, dest: Path) -> bool:
    """Download the HQ (or LQ) MP3 preview of a Freesound result to *dest*."""
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



def _generate_queries_from_locations(locations: list[str]) -> list[list[str]]:
    """Use Haiku to turn location descriptions into Freesound search queries."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    numbered = "\n".join(f"{i+1}. {loc}" for i, loc in enumerate(locations))
    prompt = (
        "You are a sound designer. For each location below, generate 3 Freesound.org search queries "
        "for ambient background sound — from most specific to most general.\n"
        "Rules:\n"
        "- Short keyword phrases (2-4 words)\n"
        "- Focus on the acoustic character of the place\n"
        "- Each query must be different, third must be generic enough to always return results\n"
        "- Return ONLY valid JSON array: [[q1,q2,q3], ...]\n\n"
        f"Locations:\n{numbered}"
    )
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
        timeout=30.0,
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
    print(f"[ambient] START book={book} ch={chapter_id} engine={engine}")
    _set_ambient_status(book, chapter_id, engine, "running")

    from backend.database import SessionLocal
    try:
        # Phase 1: read-only — get scene data then close the session immediately
        db = SessionLocal()
        try:
            db_book = db.query(Book).filter(Book.slug == book).first()
            if not db_book:
                raise ValueError("Book not found in DB")
            db_chapter = db.query(Chapter).filter(
                Chapter.book_id == db_book.id,
                Chapter.chapter_id == chapter_id,
            ).first()
            if not db_chapter:
                raise ValueError("Chapter not found in DB")
            scene_ranges = _get_scene_ranges_from_db(db, db_chapter, engine)
        finally:
            db.close()

        print(f"[ambient] {len(scene_ranges)} scenes found")
        if not scene_ranges:
            raise ValueError("No scenes found — run scene detection pipeline step first")

        # Phase 2: external API calls (no DB session held)
        freesound_key = os.environ.get("FREESOUND_API_KEY", "")
        locations = [r["location"] or "indoor quiet room" for r in scene_ranges]
        print(f"[ambient] calling Anthropic for {len(locations)} locations...")
        queries_per_scene = _generate_queries_from_locations(locations)
        print(f"[ambient] Anthropic done, got {len(queries_per_scene)} query sets")

        results = []
        for queries, rng in zip(queries_per_scene, scene_ranges):
            sound_url = None
            if freesound_key:
                for q in queries:
                    result = _freesound_search(q, freesound_key)
                    if result:
                        dest = AMBIENT_CACHE / f"{result['id']}.mp3"
                        if _freesound_download(result, dest):
                            sound_url = f"/ambient-files/{result['id']}.mp3"
                            break
                    time.sleep(0.3)
            results.append((queries, rng, sound_url))

        # Phase 3: write — open a fresh session just for the DB writes
        db = SessionLocal()
        try:
            scene_ids = [r["scene_id"] for r in scene_ranges]
            db.query(AmbientScene).filter(
                AmbientScene.scene_id.in_(scene_ids),
                AmbientScene.engine == engine,
            ).delete(synchronize_session=False)

            for queries, rng, sound_url in results:
                db.add(AmbientScene(
                    scene_id=rng["scene_id"],
                    engine=engine,
                    start=rng["start"],
                    end=rng["end"],
                    sound_url=sound_url,
                    queries=json.dumps(queries),
                ))

            db.commit()
        finally:
            db.close()

        print(f"[ambient] DONE book={book} ch={chapter_id}")
        _set_ambient_status(book, chapter_id, engine, "done")

    except Exception as e:
        print(f"[ambient] ERROR book={book} ch={chapter_id}: {e}")
        _set_ambient_status(book, chapter_id, engine, "error", str(e))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{book}/chapters/{chapter_id}/ambient/generate")
def generate_ambient(book: str, chapter_id: int, background_tasks: BackgroundTasks,
                     engine: str = "elevenlabs", db_book: Book = Depends(get_owned_book)):
    """Start ambient sound generation for a chapter (runs in background)."""
    status_path = STORAGE_DIR / book / "audio" / engine / f"chapter_{chapter_id:02d}_ambient_status.json"

    if status_path.exists():
        data = _load_json(status_path)
        if data.get("status") == "running":
            age = time.time() - status_path.stat().st_mtime
            if age < 180:  # allow restart if stuck for more than 3 minutes
                raise HTTPException(409, "Ambient generation already running")

    background_tasks.add_task(_generate_ambient_bg, book, chapter_id, engine)
    return {"ok": True, "status": "started"}


@router.get("/{book}/chapters/{chapter_id}/ambient")
def get_ambient(book: str, chapter_id: int, engine: str = "elevenlabs",
                db: Session = Depends(get_db), db_book: Book = Depends(get_owned_book)):
    """Return ambient config + generation status for a chapter."""
    # Check status file
    status_path = STORAGE_DIR / book / "audio" / engine / f"chapter_{chapter_id:02d}_ambient_status.json"
    status = "none"
    if status_path.exists():
        status = _load_json(status_path).get("status", "none")

    db_chapter = db.query(Chapter).filter(
        Chapter.book_id == db_book.id,
        Chapter.chapter_id == chapter_id,
    ).first()
    if not db_chapter:
        return {"status": status, "scenes": []}

    db_scenes = (db.query(Scene)
                   .filter(Scene.chapter_id == db_chapter.id)
                   .order_by(Scene.scene_index)
                   .all())

    scene_ids = [s.id for s in db_scenes]
    ambient_rows = (db.query(AmbientScene)
                      .filter(AmbientScene.scene_id.in_(scene_ids),
                              AmbientScene.engine == engine)
                      .all())

    ambient_by_scene = {a.scene_id: a for a in ambient_rows}

    return {
        "status": "done" if ambient_rows else status,
        "scenes": [
            {
                "scene_index": s.scene_index,
                "scene_id":    s.id,
                "preview":     s.preview or "",
                "location":    s.location or "",
                "start":       ambient_by_scene[s.id].start     if s.id in ambient_by_scene else None,
                "end":         ambient_by_scene[s.id].end       if s.id in ambient_by_scene else None,
                "sound_url":   ambient_by_scene[s.id].sound_url if s.id in ambient_by_scene else None,
                "queries":     json.loads(str(ambient_by_scene[s.id].queries))
                               if s.id in ambient_by_scene and ambient_by_scene[s.id].queries else [],
            }
            for s in db_scenes
        ],
    }




# ── GET /books/{book}/ambient/search ─────────────────────────────────────────

@router.get("/{book}/ambient/search")
def ambient_search(book: str, q: str, db_book: Book = Depends(get_owned_book)):
    """Search Freesound by keyword, return 5 results with preview URLs."""
    api_key = os.environ.get("FREESOUND_API_KEY", "")
    if not api_key:
        raise HTTPException(400, "FREESOUND_API_KEY not configured")
    try:
        r = requests.get(
            f"{FREESOUND_URL}/search/text/",
            params={
                "query":     q,
                "fields":    "id,name,duration,previews",
                "filter":    "duration:[20 TO *]",
                "sort":      "rating_desc",
                "page_size": 5,
                "token":     api_key,
            },
            timeout=6,
        )
        results = r.json().get("results", [])
        return {
            "results": [
                {
                    "id":          s["id"],
                    "name":        s["name"],
                    "duration":    round(s["duration"]),
                    "preview_url": s["previews"].get("preview-hq-mp3") or s["previews"].get("preview-lq-mp3"),
                }
                for s in results
            ]
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ── POST /books/{book}/chapters/{chapter_id}/ambient/assign ───────────────────

class AssignAmbientRequest(BaseModel):
    sound_id:    int
    preview_url: str
    engine:      str = "elevenlabs"


@router.post("/{book}/chapters/{chapter_id}/ambient/assign")
def assign_ambient(book: str, chapter_id: int, body: AssignAmbientRequest,
                   db: Session = Depends(get_db), db_book: Book = Depends(get_owned_book)):
    """Download a Freesound preview and assign it to all scenes of a chapter."""
    db_chapter = db.query(Chapter).filter(
        Chapter.book_id    == db_book.id,
        Chapter.chapter_id == chapter_id,
    ).first()
    if not db_chapter:
        raise HTTPException(404, "Chapter not found")

    # Download preview to cache
    dest      = AMBIENT_CACHE / f"{body.sound_id}.mp3"
    sound_url = f"/ambient-files/{body.sound_id}.mp3"
    if not dest.exists():
        try:
            resp = requests.get(body.preview_url, timeout=30)
            if resp.status_code != 200:
                raise HTTPException(502, "Failed to download sound from Freesound")
            AMBIENT_CACHE.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, str(e))

    scenes = db.query(Scene).filter(Scene.chapter_id == db_chapter.id).all()
    if not scenes:
        raise HTTPException(400, "No scenes found — run scene detection first")

    scene_ids = [s.id for s in scenes]
    db.query(AmbientScene).filter(
        AmbientScene.scene_id.in_(scene_ids),
        AmbientScene.engine == body.engine,
    ).delete(synchronize_session=False)

    for scene in scenes:
        para_ids = [p.id for p in db.query(Paragraph).filter(Paragraph.scene_id == scene.id).all()]
        ts_rows  = db.query(ParagraphTimestamp).filter(
            ParagraphTimestamp.paragraph_id.in_(para_ids),
            ParagraphTimestamp.engine == body.engine,
        ).all() if para_ids else []

        scene_id: int = scene.id  # type: ignore[assignment]
        ts_start, ts_end = _ts_start_end(ts_rows)
        db.add(AmbientScene(
            scene_id  = scene_id,
            engine    = body.engine,
            start     = ts_start,
            end       = ts_end,
            sound_url = sound_url,
            queries   = json.dumps([]),
        ))

    db.commit()

    # Write done status file so ChapterPage picks it up
    status_path = STORAGE_DIR / book / "audio" / body.engine / f"chapter_{chapter_id:02d}_ambient_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({"status": "done", "error": ""}))

    return {"ok": True, "sound_url": sound_url}


# ── POST /books/scenes/{scene_id}/ambient/assign ──────────────────────────────

class AssignSceneAmbientRequest(BaseModel):
    sound_id:    int
    preview_url: str
    engine:      str = "elevenlabs"


@router.post("/scenes/{scene_id}/ambient/assign")
def assign_scene_ambient(scene_id: int, body: AssignSceneAmbientRequest,
                         db: Session = Depends(get_db), scene: Scene = Depends(get_owned_scene)):
    """Download a Freesound preview and assign it to a specific scene."""
    dest      = AMBIENT_CACHE / f"{body.sound_id}.mp3"
    sound_url = f"/ambient-files/{body.sound_id}.mp3"
    if not dest.exists():
        try:
            resp = requests.get(body.preview_url, timeout=30)
            if resp.status_code != 200:
                raise HTTPException(502, "Failed to download sound from Freesound")
            AMBIENT_CACHE.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, str(e))

    para_ids = [p.id for p in db.query(Paragraph).filter(Paragraph.scene_id == scene_id).all()]
    ts_rows  = db.query(ParagraphTimestamp).filter(
        ParagraphTimestamp.paragraph_id.in_(para_ids),
        ParagraphTimestamp.engine == body.engine,
    ).all() if para_ids else []

    existing = db.query(AmbientScene).filter(
        AmbientScene.scene_id == scene_id,
        AmbientScene.engine   == body.engine,
    ).first()

    ts_start, ts_end = _ts_start_end(ts_rows)
    if existing:
        existing.sound_url = sound_url
        if ts_start is not None:
            existing.start = ts_start
            existing.end   = ts_end
    else:
        db.add(AmbientScene(
            scene_id  = scene_id,
            engine    = body.engine,
            start     = ts_start,
            end       = ts_end,
            sound_url = sound_url,
            queries   = json.dumps([]),
        ))

    db.commit()
    return {"ok": True, "sound_url": sound_url}