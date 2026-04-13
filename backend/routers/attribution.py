import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

STORAGE_DIR = Path("storage/uploads")


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def get_src_path(book: str) -> Path:
    base = STORAGE_DIR / book
    for name in ("ground_truth_fixed.json", "parsed_with_scenes.json", "parsed_final.json", "parsed.json"):
        p = base / name
        if p.exists():
            return p
    raise HTTPException(status_code=404, detail=f"No parsed data for book '{book}'")


class SpeakerUpdate(BaseModel):
    speaker: str | None


# ── PUT /books/{book}/chapters/{chapter_id}/paragraphs/{para_index}/speaker ──

@router.put("/{book}/chapters/{chapter_id}/paragraphs/{para_index}/speaker")
def update_speaker(book: str, chapter_id: int, para_index: int, body: SpeakerUpdate):
    """Correct the speaker for a dialogue paragraph."""
    src_path = get_src_path(book)
    data = load_json(src_path)

    chapter = next((ch for ch in data["chapters"] if ch["id"] == chapter_id), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_id} not found")

    if "paragraphs" in chapter:
        paragraphs = chapter["paragraphs"]
    else:
        paragraphs = [
            p
            for scene in chapter.get("scenes", [])
            for p in scene["paragraphs"]
        ]

    if para_index >= len(paragraphs):
        raise HTTPException(status_code=404, detail=f"Paragraph {para_index} not found")

    para = paragraphs[para_index]
    if para["type"] != "dialogue":
        raise HTTPException(status_code=400, detail="Only dialogue paragraphs can have a speaker")

    para["speaker_ground_truth"] = body.speaker

    save_json(src_path, data)

    return {"ok": True, "index": para_index, "speaker": body.speaker}


# ── GET /books/{book}/chapters/{chapter_id}/speakers ─────────────────────────

@router.get("/{book}/chapters/{chapter_id}/speakers")
def get_speakers(book: str, chapter_id: int):
    """Get all unique speakers in a chapter."""
    src_path = get_src_path(book)
    data = load_json(src_path)

    chapter = next((ch for ch in data["chapters"] if ch["id"] == chapter_id), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_id} not found")

    if "paragraphs" in chapter:
        paragraphs = chapter["paragraphs"]
    else:
        paragraphs = [
            p
            for scene in chapter.get("scenes", [])
            for p in scene["paragraphs"]
        ]

    speakers = sorted({
        p.get("speaker_ground_truth") or p.get("speaker")
        for p in paragraphs
        if p["type"] == "dialogue" and (p.get("speaker_ground_truth") or p.get("speaker"))
    })

    return {"chapter_id": chapter_id, "speakers": speakers}