"""Voices router: manage character voice assignments and preview TTS voices."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_owned_book
from backend.database import get_db
from backend.models import Book, Character

router = APIRouter()


# ── GET /books/{book}/characters ──────────────────────────────────────────────

@router.get("/{book}/characters")
def get_characters(book: str, db: Session = Depends(get_db), db_book: Book = Depends(get_owned_book)):
    """Get all characters for a book from DB."""
    characters = (db.query(Character)
                    .filter(Character.book_id == db_book.id)
                    .order_by(Character.name)
                    .all())

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
    db_book: Book = Depends(get_owned_book),
):
    """Update the assigned voice for a character."""
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
def list_voices(book: str, engine: str = "elevenlabs", db_book: Book = Depends(get_owned_book)):
    """List available TTS voices for an engine."""
    if engine == "elevenlabs":
        from core.tts.elevenlabs_tts import ElevenLabsTTS
        return {"engine": engine, "voices": ElevenLabsTTS().list_voices()}
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
def preview_voice(book: str, body: PreviewRequest, db: Session = Depends(get_db),
                  db_book: Book = Depends(get_owned_book)):
    """Synthesize a short text sample and return audio bytes."""
    import tempfile, os
    from fastapi.responses import Response

    if body.engine == "elevenlabs":
        from core.tts.elevenlabs_tts import ElevenLabsTTS
        tts = ElevenLabsTTS()
    elif body.engine == "xtts":
        from core.tts.xtts_tts import XttsTTS
        tts = XttsTTS()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown engine: {body.engine}")

    # Apply character voice settings if char_id provided and engine is elevenlabs
    voice_settings = None
    if body.char_id and body.engine == "elevenlabs":
        char = db.query(Character).filter(
            Character.id == body.char_id,
            Character.book_id == db_book.id,
        ).first()
        if char and char.voice_stability is not None:
            from elevenlabs.types import VoiceSettings
            stability:  float = char.voice_stability          # type: ignore[assignment]
            style:      float = char.voice_style or 0.0       # type: ignore[assignment]
            sim_boost:  float = char.voice_similarity_boost or 0.75  # type: ignore[assignment]
            spk_boost:  bool  = (char.voice_speaker_boost     # type: ignore[assignment]
                                 if char.voice_speaker_boost is not None else True)
            voice_settings = VoiceSettings(
                stability=stability,
                style=style,
                similarity_boost=sim_boost,
                use_speaker_boost=spk_boost,
            )

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    tts.synthesize(body.text[:300], body.voice_id, output_path=Path(tmp_path),
                   voice_settings=voice_settings)

    with open(tmp_path, "rb") as f:
        audio_bytes = f.read()

    os.unlink(tmp_path)

    return Response(content=audio_bytes, media_type="audio/mpeg")