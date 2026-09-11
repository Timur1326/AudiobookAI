"""Chapter synthesis: text → MP3 using TTS engines."""

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from pydub import AudioSegment

load_dotenv()

# ── Narrator style settings ───────────────────────────────────────────────────

NARRATOR_STYLES = {
    "theatrical": {
        "stability": 0.15,
        "similarity_boost": 0.60,
        "style": 0.90,
        "use_speaker_boost": True,
    },
    "documentary": {
        "stability": 0.92,
        "similarity_boost": 0.80,
        "style": 0.00,
        "use_speaker_boost": False,
    },
}


STORAGE_DIR = Path("storage/uploads")

# Silence (ms) inserted between consecutive paragraphs based on their types.
PAUSE: dict[tuple[str, str], int] = {
    ("narration", "narration"): 200,
    ("narration", "dialogue"):  400,
    ("dialogue",  "narration"): 300,
    ("dialogue",  "dialogue"):  150,
}
DEFAULT_PAUSE = 300


def make_tts(engine: str):
    """Instantiate and return the TTS backend for the given engine name."""
    if engine == "elevenlabs":
        from core.tts.elevenlabs_tts import ElevenLabsTTS
        return ElevenLabsTTS()
    if engine == "xtts":
        from core.tts.xtts_tts import XttsTTS
        return XttsTTS()
    raise ValueError(f"Unknown engine: {engine}. Use: elevenlabs, xtts")


def default_voice(engine: str) -> str:
    """Return the default narrator voice ID / path for the given engine."""
    defaults = {
        "elevenlabs": "SAz9YHcvj6GT2YYXdXww",
        "xtts":       "storage/voices/narrator.mp3",
    }
    return defaults[engine]


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)





def get_voice(speaker: str | None, voice_map: dict, narrator_voice: str) -> str:
    """Return the voice ID for a speaker, falling back to narrator if not found.

    Tries exact match first, then partial substring match against known names.
    """
    if not speaker:
        return voice_map.get("NARRATOR", narrator_voice)
    s = speaker.strip()
    if s in voice_map:
        return voice_map[s]
    # Fuzzy fallback: check if speaker contains or is contained by a known name
    s_lower = s.lower()
    for key in voice_map:
        if key == "NARRATOR":
            continue
        k_lower = key.lower()
        if s_lower in k_lower or k_lower in s_lower:
            return voice_map[key]
    return voice_map.get("NARRATOR", narrator_voice)




def _auto_build_xtts_map(book_slug: str, book_id: int, db, DBCharacter) -> None:
    """Build voice_map_xtts.json from DB characters + ElevenLabs preview downloads.

    Used as a fallback when step 6 was run before voice_map_elevenlabs.json was introduced.
    """
    vm_path = STORAGE_DIR / book_slug / "voice_map_elevenlabs.json"
    if not vm_path.exists():
        chars = db.query(DBCharacter).filter(
            DBCharacter.book_id == book_id,
            DBCharacter.voice_id.isnot(None),
        ).all()
        if not chars:
            return
        vm = {c.name: c.voice_id for c in chars}
        vm_path.parent.mkdir(parents=True, exist_ok=True)
        with open(vm_path, "w", encoding="utf-8") as f:
            json.dump(vm, f, ensure_ascii=False, indent=2)
        print(f"Auto-generated voice_map_elevenlabs.json from DB ({len(vm)} characters)")

    try:
        from core.tts.download_voices import download_voices
        download_voices(book_slug)
    except Exception as e:
        print(f"Warning: voice download failed: {e}")


def _build_voice_map(engine: str, book_slug: str, book_id: int, db) -> tuple[dict, list]:
    """Load {character_name: voice_id} and the list of Character DB objects.

    For XTTS the voice map is read from voice_map_xtts.json (reference audio paths).
    For ElevenLabs it is built from Character.voice_id stored in DB.
    Returns (voice_map, chars).
    """
    from backend.models import Character as DBCharacter

    if engine == "xtts":
        xtts_map_path = STORAGE_DIR / book_slug / "voice_map_xtts.json"
        if not xtts_map_path.exists():
            _auto_build_xtts_map(book_slug, book_id, db, DBCharacter)
        voice_map = _load_json(xtts_map_path) if xtts_map_path.exists() else {}
        chars = db.query(DBCharacter).filter(
            DBCharacter.book_id == book_id,
            DBCharacter.voice_id.isnot(None),
        ).all()
    else:
        chars = db.query(DBCharacter).filter(
            DBCharacter.book_id == book_id,
            DBCharacter.engine == engine,
            DBCharacter.voice_id.isnot(None),
        ).all()
        voice_map = {c.name: c.voice_id for c in chars}
        for c in chars:
            for alias in c.aliases:
                voice_map[alias.alias] = c.voice_id

    return voice_map, chars


def _build_style_map(engine: str, chars: list) -> dict:
    """Build {character_name: VoiceSettings} for ElevenLabs characters that have style data."""
    style_map: dict = {}
    if engine != "elevenlabs":
        return style_map
    from elevenlabs.types import VoiceSettings
    for c in chars:
        if c.voice_stability is not None:
            settings = VoiceSettings(
                stability        = c.voice_stability,
                style            = c.voice_style            or 0.0,
                similarity_boost = c.voice_similarity_boost or 0.75,
                use_speaker_boost= c.voice_speaker_boost    if c.voice_speaker_boost is not None else True,
            )
            style_map[c.name] = settings
            for alias in c.aliases:
                style_map[alias.alias] = settings
    return style_map


def _synthesize_segments(
    paragraphs: list[dict],
    tts,
    voice_map: dict,
    narrator_voice: str,
    style_map: dict,
    narrator_voice_settings,
    output_dir: Path,
) -> list[tuple[Path, str]]:
    """Synthesize each paragraph to an MP3 segment file, skipping already-done files.

    Returns list of (segment_path, paragraph_type) in order.
    """
    segments: list[tuple[Path, str]] = []
    use_voice_map = bool(voice_map)

    for i, para in enumerate(paragraphs):
        text = para.get("text", "").strip()
        if not text:
            continue

        speaker   = para.get("speaker")
        para_type = para.get("type", "narration")
        voice_id  = get_voice(speaker, voice_map, narrator_voice) if use_voice_map else narrator_voice
        out_file  = output_dir / f"{i:04d}.mp3"

        if out_file.exists() and out_file.stat().st_size > 0:
            segments.append((out_file, para_type))
            continue

        label = f"({speaker})" if speaker else "(narrator)"
        print(f"  [{i+1}/{len(paragraphs)}] {label} {text[:60]}...")

        if para_type != "dialogue":
            vs = narrator_voice_settings
        else:
            vs = style_map.get(speaker) if speaker else None
            if vs is None and speaker:
                # Fuzzy fallback: partial name match in style_map
                s_lower = speaker.lower()
                for key in style_map:
                    if s_lower in key.lower() or key.lower() in s_lower:
                        vs = style_map[key]
                        break

        try:
            tts.synthesize(text=text, voice_id=voice_id, output_path=out_file,
                           voice_settings=vs)
            segments.append((out_file, para_type))
        except Exception as e:
            print(f"    ERROR: {e}")

        time.sleep(0.2)

    return segments


def _merge_segments(segments: list[tuple[Path, str]]) -> tuple[AudioSegment, list[dict]]:
    """Concatenate segment MP3s with type-appropriate pauses between them.

    Returns (merged_audio, timestamps) where each timestamp has index/start/end in seconds.
    """
    combined  = AudioSegment.empty()
    timestamps: list[dict] = []
    cursor_ms = 0

    for idx, (seg, curr_type) in enumerate(segments):
        audio    = AudioSegment.from_mp3(seg)
        start_ms = cursor_ms
        end_ms   = cursor_ms + len(audio)
        para_idx = int(seg.stem)
        timestamps.append({"index": para_idx, "start": start_ms / 1000, "end": end_ms / 1000})
        combined  += audio
        cursor_ms  = end_ms

        if idx < len(segments) - 1:
            next_type = segments[idx + 1][1]
            pause_ms  = PAUSE.get((curr_type, next_type), DEFAULT_PAUSE)
            combined  += AudioSegment.silent(duration=pause_ms)
            cursor_ms += pause_ms

    return combined, timestamps


def _save_timestamps(
    timestamps: list[dict],
    db_paras: list,
    engine: str,
    ts_path: Path,
    db,
) -> None:
    """Write timestamps to JSON file and ParagraphTimestamp records in DB."""
    from backend.models import ParagraphTimestamp

    with open(ts_path, "w", encoding="utf-8") as f:
        json.dump(timestamps, f, indent=2)

    ts_by_index = {t["index"]: t for t in timestamps}
    db.query(ParagraphTimestamp).filter(
        ParagraphTimestamp.paragraph_id.in_([p.id for p in db_paras]),
        ParagraphTimestamp.engine == engine,
    ).delete(synchronize_session=False)

    for db_para in db_paras:
        ts = ts_by_index.get(db_para.index)
        if ts:
            db.add(ParagraphTimestamp(
                paragraph_id=db_para.id,
                engine=engine,
                start=ts["start"],
                end=ts["end"],
            ))


def synthesize_chapter_from_db(
    book_slug: str,
    chapter_id: int,
    engine: str,
    db,
    narrator_style: str = "theatrical",
) -> Path | None:
    """Synthesize a chapter to MP3 using paragraphs and voice assignments from DB.

    Writes segment files under storage/uploads/<book>/audio/<engine>/chapter_XX/,
    then merges them into a single MP3. Saves ParagraphTimestamp records to DB.
    """
    from backend.models import Book as DBBook, Chapter as DBChapter, Paragraph as DBParagraph

    db_book = db.query(DBBook).filter(DBBook.slug == book_slug).first()
    if not db_book:
        raise ValueError(f"Book '{book_slug}' not found in DB")

    db_chapter = db.query(DBChapter).filter(
        DBChapter.book_id == db_book.id,
        DBChapter.chapter_id == chapter_id,
    ).first()
    if not db_chapter:
        raise ValueError(f"Chapter {chapter_id} not found in DB")

    db_paras = (db.query(DBParagraph)
                  .filter(DBParagraph.chapter_id == db_chapter.id)
                  .order_by(DBParagraph.index)
                  .all())
    if not db_paras:
        raise ValueError(f"No paragraphs in DB for chapter {chapter_id}")

    voice_map, chars        = _build_voice_map(engine, book_slug, db_book.id, db)
    style_map               = _build_style_map(engine, chars)
    narrator_voice          = default_voice(engine)
    narrator_voice_settings = None

    if engine == "elevenlabs" and narrator_style in NARRATOR_STYLES:
        from elevenlabs.types import VoiceSettings
        s = NARRATOR_STYLES[narrator_style]
        narrator_voice_settings = VoiceSettings(
            stability=s["stability"],
            similarity_boost=s["similarity_boost"],
            style=s["style"],
            use_speaker_boost=s["use_speaker_boost"],
        )

    paragraphs = [{"text": p.text, "type": p.type, "speaker": p.speaker} for p in db_paras]

    print(f"\nBook:       {db_book.title}")
    print(f"Chapter:    [{chapter_id}] {db_chapter.title}")
    print(f"Engine:     {engine}")
    print(f"Paragraphs: {len(paragraphs)}")
    print(f"Voice map:  {len(voice_map)} characters")
    print(f"Style:      {narrator_style}")

    book_dir   = STORAGE_DIR / book_slug
    output_dir = book_dir / "audio" / engine / f"chapter_{chapter_id:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)

    segments = _synthesize_segments(
        paragraphs, make_tts(engine), voice_map, narrator_voice,
        style_map, narrator_voice_settings, output_dir,
    )
    if not segments:
        print("No audio segments generated.")
        return None

    print("\nMerging...")
    combined, timestamps = _merge_segments(segments)

    final_path = book_dir / "audio" / engine / f"chapter_{chapter_id:02d}.mp3"
    combined.export(str(final_path), format="mp3")

    ts_path = book_dir / "audio" / engine / f"chapter_{chapter_id:02d}_timestamps.json"
    _save_timestamps(timestamps, db_paras, engine, ts_path, db)

    db_chapter.audio_path   = str(final_path)
    db_chapter.synth_status = "done"
    db_chapter.synth_engine = engine
    db.commit()

    print(f"\nDone: {final_path}  ({len(combined)/1000:.1f}s)")
    return final_path

