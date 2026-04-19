import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Book, Character, CharacterAlias

router = APIRouter()

STORAGE_DIR = Path("storage/uploads")


def get_book_or_404(slug: str, db: Session) -> Book:
    book = db.query(Book).filter(Book.slug == slug).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Book '{slug}' not found")
    return book


# ── GET /books/{book}/characters ──────────────────────────────────────────────

@router.get("/{book}/characters")
def get_characters(book: str, db: Session = Depends(get_db)):
    """Get all characters for a book from DB."""
    db_book = get_book_or_404(book, db)
    characters = db.query(Character).filter(Character.book_id == db_book.id).all()

    return {
        "characters": [
            {
                "id":          c.id,
                "name":        c.name,
                "aliases":     [a.alias for a in c.aliases],
                "gender":      c.gender,
                "age":         c.age,
                "personality": c.personality,
                "accent":      c.accent,
                "voice_desc":  c.voice_desc,
                "sample_text": c.sample_text,
                "voice_id":    c.voice_id,
                "engine":      c.engine,
            }
            for c in characters
        ]
    }


# ── POST /books/{book}/characters/import ──────────────────────────────────────

@router.post("/{book}/characters/import")
def import_characters(book: str, db: Session = Depends(get_db)):
    """Import characters from characters.json into DB (run after pipeline step 5)."""
    db_book = get_book_or_404(book, db)

    path = STORAGE_DIR / book / "characters.json"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="characters.json not found. Run character extraction first (step 5)."
        )

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    # characters.json can be a list or {"characters": [...]}
    chars_data = raw if isinstance(raw, list) else raw.get("characters", raw)

    # Delete existing characters for this book
    db.query(Character).filter(Character.book_id == db_book.id).delete()

    imported = []
    for c in chars_data:
        name = c.get("name") or c.get("character")
        if not name:
            continue

        # Pick a sample dialogue line for preview
        sample = c.get("sample_text") or c.get("sample") or c.get("example_dialogue")
        if not sample and c.get("dialogues"):
            sample = c["dialogues"][0]

        aliases = c.get("aliases", [])

        char = Character(
            book_id=db_book.id,
            name=name,
            gender=c.get("gender"),
            age=c.get("age"),
            personality=c.get("personality"),
            accent=c.get("accent"),
            voice_desc=c.get("voice_description") or c.get("voice_desc"),
            sample_text=sample,
            voice_id=c.get("voice_id"),
            engine=c.get("engine"),
        )
        db.add(char)
        db.flush()  # get char.id
        for alias in aliases:
            if alias and alias.strip():
                db.add(CharacterAlias(character_id=char.id, alias=alias.strip()))
        imported.append(name)

    db.commit()
    return {"ok": True, "imported": len(imported), "characters": imported}


# ── PUT /books/{book}/characters/{char_id}/voice ──────────────────────────────

class VoiceUpdate(BaseModel):
    voice_id: str
    engine:   str = "elevenlabs"


@router.put("/{book}/characters/{char_id}/voice")
def update_character_voice(
    book: str,
    char_id: int,
    body: VoiceUpdate,
    db: Session = Depends(get_db),
):
    """Update the assigned voice for a character."""
    db_book = get_book_or_404(book, db)

    char = db.query(Character).filter(
        Character.id == char_id,
        Character.book_id == db_book.id,
    ).first()
    if not char:
        raise HTTPException(status_code=404, detail=f"Character {char_id} not found")

    char.voice_id = body.voice_id
    char.engine   = body.engine
    db.commit()

    return {"ok": True, "character": char.name, "voice_id": body.voice_id, "engine": body.engine}


# ── GET /books/{book}/voices ──────────────────────────────────────────────────

@router.get("/{book}/voices")
def list_voices(book: str, engine: str = "elevenlabs", lang: str = "en-US"):
    """List available TTS voices for an engine."""
    if engine == "elevenlabs":
        from core.tts.elevenlabs_tts import ElevenLabsTTS
        return {"engine": engine, "voices": ElevenLabsTTS().list_voices()}
    elif engine == "azure":
        from core.tts.azure_tts import AzureTTS
        return {"engine": engine, "voices": AzureTTS().list_voices(lang)}
    elif engine == "xtts":
        from core.tts.xtts_tts import XttsTTS
        return {"engine": engine, "voices": XttsTTS().list_voices()}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown engine: {engine}")


# ── POST /books/{book}/preview-voice ──────────────────────────────────────────

class PreviewRequest(BaseModel):
    text:       str
    voice_id:   str
    engine:     str = "elevenlabs"
    char_id:    int | None = None   # optional: apply character voice settings


@router.post("/{book}/preview-voice")
def preview_voice(book: str, body: PreviewRequest, db: Session = Depends(get_db)):
    """Synthesize a short text sample and return audio bytes."""
    import tempfile, os
    from fastapi.responses import Response

    if body.engine == "elevenlabs":
        from core.tts.elevenlabs_tts import ElevenLabsTTS
        tts = ElevenLabsTTS()
    elif body.engine == "azure":
        from core.tts.azure_tts import AzureTTS
        tts = AzureTTS()
    elif body.engine == "xtts":
        from core.tts.xtts_tts import XttsTTS
        tts = XttsTTS()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown engine: {body.engine}")

    # Apply character voice settings if char_id provided and engine is elevenlabs
    voice_settings = None
    if body.char_id and body.engine == "elevenlabs":
        db_book = get_book_or_404(book, db)
        char = db.query(Character).filter(
            Character.id == body.char_id,
            Character.book_id == db_book.id,
        ).first()
        if char and char.voice_stability is not None:
            from elevenlabs.types import VoiceSettings
            voice_settings = VoiceSettings(
                stability        = char.voice_stability,
                style            = char.voice_style            or 0.0,
                similarity_boost = char.voice_similarity_boost or 0.75,
                use_speaker_boost= char.voice_speaker_boost    if char.voice_speaker_boost is not None else True,
            )

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    tts.synthesize(body.text[:300], body.voice_id, output_path=tmp_path,
                   voice_settings=voice_settings)

    with open(tmp_path, "rb") as f:
        audio_bytes = f.read()

    os.unlink(tmp_path)

    return Response(content=audio_bytes, media_type="audio/mpeg")


# ── POST /books/{book}/assign-voices ─────────────────────────────────────────

@router.post("/{book}/assign-voices")
def assign_voices(book: str, engine: str = "elevenlabs", db: Session = Depends(get_db)):
    """Run LLM voice assignment and save results to DB."""
    db_book = get_book_or_404(book, db)

    from core.nlp.voice_assigner import run as voice_run
    voice_run(book)

    # Read the generated voice_map and update DB characters
    voice_map_path = STORAGE_DIR / book / f"voice_map_{engine}.json"
    if voice_map_path.exists():
        with open(voice_map_path, encoding="utf-8") as f:
            voice_map = json.load(f)

        characters = db.query(Character).filter(Character.book_id == db_book.id).all()
        for char in characters:
            if char.name in voice_map:
                char.voice_id = voice_map[char.name]
                char.engine   = engine
        db.commit()

    return {"ok": True, "assigned": len(voice_map) if voice_map_path.exists() else 0}