"""
Synthesize a chapter of the book into audio using TTS engines.

Usage:
    python synthesize_chapter.py alice 11                   # chapter 11 with default settings
    python synthesize_chapter.py alice 11 --assign          # interactively assign voices to characters before synthesis
    python synthesize_chapter.py alice 11 --voice-map       # use previously saved voice map
    python synthesize_chapter.py alice 11 --engine openai   # engine: azure, elevenlabs, xtts
    python synthesize_chapter.py --list-voices              # show available voices for the default engine
    python synthesize_chapter.py --list-voices --engine azure --lang en-GB
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

import anthropic
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

NARRATOR_STYLE_PROMPTS = {
    "theatrical": (
        "You are marking up text for a theatrical BBC Radio Drama actor. "
        "You MUST add punctuation pauses — the original text needs your direction.\n\n"
        "Example:\n"
        "  Input:  1. The fire burned brightly and the soft radiance caught the bubbles.\n"
        "  Output: 1. The fire burned brightly... and the soft radiance—caught the bubbles.\n\n"
        "Rules:\n"
        "- Use '...' before the most emotionally charged moment in a sentence\n"
        "- Use '—' before a vivid image or unexpected phrase\n"
        "- Add at most 1-2 pauses per sentence. Restraint is power.\n"
        "- Do NOT change, reorder, add, or remove any words. Punctuation only.\n"
        "- Keep the numbered format exactly: '1. text', '2. text', etc.\n\n"
        "Return only the numbered list, nothing else."
    ),
    "documentary": (
        "You are preparing text for a David Attenborough-style documentary narrator. "
        "Calm, authoritative, precise. No drama.\n\n"
        "Rules:\n"
        "- Split any very long sentence into two shorter cleaner sentences where natural\n"
        "- Remove any '...' or '—'; replace with comma or period\n"
        "- Do NOT change any individual words\n"
        "- Keep the numbered format exactly: '1. text', '2. text', etc.\n\n"
        "Return only the numbered list, nothing else."
    ),
}


def adapt_narrator_paragraphs(paragraphs: list[dict], style: str) -> list[dict]:
    """
    Batch-adapt narrator paragraph texts for a given narrator style using Claude.
    Returns a new list with adapted 'text' fields (non-narrator paragraphs unchanged).
    """
    if style not in NARRATOR_STYLE_PROMPTS:
        return paragraphs

    narrator_indices = [
        i for i, p in enumerate(paragraphs)
        if p.get("type", "narration") != "dialogue" and p.get("text", "").strip()
    ]
    if not narrator_indices:
        return paragraphs

    CHUNK = 25  # max paragraphs per request
    adapted_texts: dict[int, str] = {}

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = NARRATOR_STYLE_PROMPTS[style]

    for chunk_start in range(0, len(narrator_indices), CHUNK):
        chunk = narrator_indices[chunk_start: chunk_start + CHUNK]
        numbered = "\n".join(
            f"{j + 1}. {paragraphs[i]['text']}" for j, i in enumerate(chunk)
        )
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": f"{prompt}\n\n{numbered}"}],
        )
        raw = message.content[0].text.strip()

        for line in raw.splitlines():
            m = re.match(r"^(\d+)\.\s+(.*)", line.strip())
            if m:
                local_idx = int(m.group(1)) - 1
                if 0 <= local_idx < len(chunk):
                    adapted_texts[chunk[local_idx]] = m.group(2).strip()

    result = [dict(p) for p in paragraphs]
    for i, adapted in adapted_texts.items():
        if adapted:
            result[i] = {**result[i], "text": adapted}
    return result

STORAGE_DIR = Path("storage/uploads")



def make_tts(engine: str):
    if engine == "azure":
        from core.tts.azure_tts import AzureTTS
        return AzureTTS()
    if engine == "elevenlabs":
        from core.tts.elevenlabs_tts import ElevenLabsTTS
        return ElevenLabsTTS()
    if engine == "xtts":
        from core.tts.xtts_tts import XttsTTS
        return XttsTTS()
    raise ValueError(f"Unknown engine: {engine}. Use: azure, elevenlabs, xtts")


def default_voice(engine: str) -> str:
    defaults = {
        "azure":      "en-US-BrianNeural",
        "elevenlabs": "SAz9YHcvj6GT2YYXdXww",
        "xtts":       "storage/voices/narrator.wav",
    }
    return defaults[engine]



def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def voice_map_path(book: str, engine: str) -> Path:
    return STORAGE_DIR / book / f"voice_map_{engine}.json"


def load_voice_map(book: str, engine: str) -> dict:
    path = voice_map_path(book, engine)
    if path.exists():
        return load_json(path)
    return {"NARRATOR": default_voice(engine)}


def build_alias_map(book: str, voice_map: dict) -> dict[str, str]:
    """Build {alias -> voice_id} from characters.json aliases."""
    chars_path = STORAGE_DIR / book / "characters.json"
    if not chars_path.exists():
        return {}
    characters = load_json(chars_path)
    alias_map: dict[str, str] = {}
    for char in characters:
        name     = char["name"]
        voice_id = voice_map.get(name)
        if not voice_id:
            continue
        for alias in char.get("aliases", []):
            if alias not in voice_map:
                alias_map[alias] = voice_id
    return alias_map


def save_voice_map(vm: dict, book: str, engine: str) -> None:
    path = voice_map_path(book, engine)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(vm, f, ensure_ascii=False, indent=2)
    print(f"Voice map is saved: {path}")



def get_chapter_speakers(chapter: dict) -> list[str]:
    seen = set()
    for p in chapter["paragraphs"]:
        if p["type"] != "dialogue":
            continue
        s = p.get("speaker_ground_truth") or p.get("speaker")
        if s:
            seen.add(s.strip())
    return sorted(seen)



def assign_voices_interactively(
    speakers: list[str],
    voices: list[dict],
    voice_map: dict,
) -> dict:
    print("\nAvailable voices:")
    print(f"  {'№':<5} {'ID':<35} {'Name':<25} {'Gender'}")
    print("  " + "-" * 75)
    for i, v in enumerate(voices):
        gender = v.get("gender", v.get("category", ""))
        print(f"  {i:<5} {v['id']:<35} {v['name']:<25} {gender}")

    print("\nAssign voice (Enter = keep the current, number or voice_id):\n")

    for speaker in ["NARRATOR"] + speakers:
        current_id = voice_map.get(speaker, "—")
        current_name = next((v["name"] for v in voices if v["id"] == current_id), current_id[:20])
        try:
            raw = input(f"  {speaker:<25} [now is: {current_name}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue
        if raw.isdigit() and int(raw) < len(voices):
            voice_map[speaker] = voices[int(raw)]["id"]
            print(f"    → {voices[int(raw)]['name']}")
        else:
            voice_map[speaker] = raw

    return voice_map



def get_voice(speaker: str | None, voice_map: dict, alias_map: dict, narrator_voice: str) -> str:
    if not speaker:
        return voice_map.get("NARRATOR", narrator_voice)
    s = speaker.strip()
    if s in voice_map:
        return voice_map[s]
    if s in alias_map:
        return alias_map[s]
    return voice_map.get("NARRATOR", narrator_voice)


def synthesize_chapter(
    book: str,
    chapter_idx: int,
    engine: str,
    voice_map: dict,
    use_voice_map: bool,
    narrator_style: str = "standard",
) -> Path:
    tts = make_tts(engine)
    narrator_voice = default_voice(engine)

    book_dir = STORAGE_DIR / book
    for name in ("ground_truth_fixed.json", "parsed_with_scenes.json", "parsed_final.json"):
        src_path = book_dir / name
        if src_path.exists():
            break
    data = load_json(src_path)
    alias_map = build_alias_map(book, voice_map)

    chapters = data["chapters"]
    if chapter_idx >= len(chapters):
        raise ValueError(f"Chapter {chapter_idx} no exist (all {len(chapters)})")

    chapter = chapters[chapter_idx]
    if "paragraphs" in chapter:
        paragraphs = chapter["paragraphs"]
    else:
        paragraphs = [p for scene in chapter.get("scenes", []) for p in scene["paragraphs"]]

    print(f"\nBook:    {data['title']}")
    print(f"Chapter:    [{chapter['id']}] {chapter['title']}")
    print(f"Engine:   {engine}")
    print(f"Voices:   {'per character' if use_voice_map else 'one narrator voice'}")
    print(f"Style:    {narrator_style}")
    print(f"Paragraphs: {len(paragraphs)}")

    # ── Narrator style: batch-adapt narrator paragraphs with LLM ────────────────
    if narrator_style != "standard" and engine == "elevenlabs":
        print(f"\nAdapting narrator paragraphs for '{narrator_style}' style...")
        paragraphs = adapt_narrator_paragraphs(paragraphs, narrator_style)
        print("  Done.")

    # ── ElevenLabs narrator voice settings per style ─────────────────────────────
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

    output_dir = book_dir / "audio" / engine / f"chapter_{chapter['id']:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)

    segments: list[tuple[Path, str]] = []  # (path, para_type)

    for i, para in enumerate(paragraphs):
        text = para.get("text", "").strip()
        if not text:
            continue

        speaker   = (para.get("speaker_ground_truth")
                     or para.get("speaker_llm_context")
                     or para.get("speaker"))
        para_type = para.get("type", "narration")
        voice_id  = get_voice(speaker, voice_map, alias_map, narrator_voice) if use_voice_map else narrator_voice
        out_file  = output_dir / f"{i:04d}.mp3"

        if out_file.exists() and out_file.stat().st_size > 0:
            print(f"  [{i+1}/{len(paragraphs)}] skip")
            segments.append((out_file, para_type))
            continue

        label = f"({speaker})" if speaker else "(narrator)"
        print(f"  [{i+1}/{len(paragraphs)}] {label} {text[:60]}...")

        # Apply narrator style voice settings only for narrator paragraphs
        is_narrator = para_type != "dialogue"
        vs = narrator_voice_settings if (is_narrator and narrator_voice_settings) else None

        try:
            tts.synthesize(text=text, voice_id=voice_id, output_path=out_file,
                           voice_settings=vs)
            segments.append((out_file, para_type))
        except Exception as e:
            print(f"    ERROR: {e}")
            continue

        time.sleep(0.2)

    if not segments:
        print("No audio segments were generated.")
        return None

    PAUSE = {
        ("narration",  "narration"):  200,
        ("narration",  "dialogue"):   400,
        ("dialogue",   "narration"):  300,
        ("dialogue",   "dialogue"):   150,
    }
    DEFAULT_PAUSE = 300

    print("\nMerging audio files...")
    combined  = AudioSegment.empty()
    timestamps = []
    cursor_ms  = 0

    for idx, (seg, curr_type) in enumerate(segments):
        audio     = AudioSegment.from_mp3(seg)
        start_ms  = cursor_ms
        end_ms    = cursor_ms + len(audio)
        # seg filename is {i:04d}.mp3 — para index == int(stem)
        para_idx  = int(seg.stem)
        timestamps.append({"index": para_idx, "start": start_ms / 1000, "end": end_ms / 1000})
        combined  += audio
        cursor_ms  = end_ms

        if idx < len(segments) - 1:
            next_type = segments[idx + 1][1]
            pause_ms  = PAUSE.get((curr_type, next_type), DEFAULT_PAUSE)
            combined  += AudioSegment.silent(duration=pause_ms)
            cursor_ms += pause_ms

    final_path = book_dir / "audio" / engine / f"chapter_{chapter['id']:02d}.mp3"
    combined.export(str(final_path), format="mp3")

    ts_path = book_dir / "audio" / engine / f"chapter_{chapter['id']:02d}_timestamps.json"
    with open(ts_path, "w", encoding="utf-8") as f:
        json.dump(timestamps, f, indent=2)

    print(f"\nГотово: {final_path}  ({len(combined)/1000:.1f} сек)")
    return final_path


def build_timestamps_from_segments(book: str, chapter_id: int, engine: str) -> Path | None:
    """
    Reconstruct timestamps from already-synthesized segment files.
    Used for chapters synthesized before timestamps were introduced.
    """
    book_dir   = STORAGE_DIR / book
    seg_dir    = book_dir / "audio" / engine / f"chapter_{chapter_id:02d}"
    ts_path    = book_dir / "audio" / engine / f"chapter_{chapter_id:02d}_timestamps.json"

    if not seg_dir.exists():
        return None

    # Load source data to get paragraph types for pause calculation
    for name in ("parsed_with_scenes.json", "ground_truth_fixed.json", "parsed_final.json"):
        src = book_dir / name
        if src.exists():
            data = load_json(src)
            break
    else:
        return None

    chapters = data["chapters"]
    ch = next((c for c in chapters if c["id"] == chapter_id), None)
    if ch is None:
        return None

    if "paragraphs" in ch:
        paragraphs = ch["paragraphs"]
    else:
        paragraphs = [p for scene in ch.get("scenes", []) for p in scene["paragraphs"]]

    PAUSE = {
        ("narration", "narration"): 200,
        ("narration", "dialogue"):  400,
        ("dialogue",  "narration"): 300,
        ("dialogue",  "dialogue"):  150,
    }
    DEFAULT_PAUSE = 300

    segs = sorted(seg_dir.glob("*.mp3"), key=lambda p: int(p.stem))
    if not segs:
        return None

    timestamps = []
    cursor_ms  = 0

    for idx, seg in enumerate(segs):
        para_idx = int(seg.stem)
        audio    = AudioSegment.from_mp3(seg)
        start_ms = cursor_ms
        end_ms   = cursor_ms + len(audio)
        timestamps.append({"index": para_idx, "start": start_ms / 1000, "end": end_ms / 1000})
        cursor_ms = end_ms

        if idx < len(segs) - 1:
            curr_type = paragraphs[para_idx]["type"] if para_idx < len(paragraphs) else "narration"
            next_idx  = int(segs[idx + 1].stem)
            next_type = paragraphs[next_idx]["type"] if next_idx < len(paragraphs) else "narration"
            pause_ms  = PAUSE.get((curr_type, next_type), DEFAULT_PAUSE)
            cursor_ms += pause_ms

    with open(ts_path, "w", encoding="utf-8") as f:
        json.dump(timestamps, f, indent=2)

    return ts_path



def synthesize_chapter_from_db(
    book_slug: str,
    chapter_id: int,      # chapter_id from DB (chapter.chapter_id)
    engine: str,
    db,
    narrator_style: str = "standard",
) -> Path | None:
    """
    Synthesize a chapter reading paragraphs and voice assignments from the database.
    Writes ParagraphTimestamp records back to DB (in addition to the JSON timestamps file).
    """
    from backend.models import (
        Book as DBBook,
        Chapter as DBChapter,
        Paragraph as DBParagraph,
        ParagraphTimestamp,
        Character as DBCharacter,
    )

    db_book = db.query(DBBook).filter(DBBook.slug == book_slug).first()
    if not db_book:
        raise ValueError(f"Book '{book_slug}' not found in DB")

    db_chapter = db.query(DBChapter).filter(
        DBChapter.book_id == db_book.id,
        DBChapter.chapter_id == chapter_id,
    ).first()
    if not db_chapter:
        raise ValueError(f"Chapter {chapter_id} not found in DB")

    # Load paragraphs from DB
    db_paras = (db.query(DBParagraph)
                  .filter(DBParagraph.chapter_id == db_chapter.id)
                  .order_by(DBParagraph.index)
                  .all())

    if not db_paras:
        raise ValueError(f"No paragraphs in DB for chapter {chapter_id}")

    # Build voice map from DB characters
    chars = db.query(DBCharacter).filter(
        DBCharacter.book_id == db_book.id,
        DBCharacter.engine == engine,
        DBCharacter.voice_id.isnot(None),
    ).all()

    voice_map = {c.name: c.voice_id for c in chars}
    # Add aliases
    for c in chars:
        for alias in c.aliases:
            voice_map[alias.alias] = c.voice_id

    # Convert DB paragraphs to dicts (reuses existing synthesis logic)
    paragraphs = [
        {
            "text":    p.text,
            "type":    p.type,
            "speaker": p.speaker,
        }
        for p in db_paras
    ]

    tts            = make_tts(engine)
    narrator_voice = default_voice(engine)
    alias_map      = {}
    use_voice_map  = bool(voice_map)

    print(f"\nBook:       {db_book.title}")
    print(f"Chapter:    [{chapter_id}] {db_chapter.title}")
    print(f"Engine:     {engine}")
    print(f"Paragraphs: {len(paragraphs)}")
    print(f"Voice map:  {len(voice_map)} characters")
    print(f"Style:      {narrator_style}")

    # Narrator style adaptation
    if narrator_style != "standard" and engine == "elevenlabs":
        print(f"\nAdapting narrator paragraphs for '{narrator_style}' style...")
        paragraphs = adapt_narrator_paragraphs(paragraphs, narrator_style)
        print("  Done.")

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

    book_dir   = STORAGE_DIR / book_slug
    output_dir = book_dir / "audio" / engine / f"chapter_{chapter_id:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)

    segments: list[tuple[Path, str]] = []

    for i, para in enumerate(paragraphs):
        text = para.get("text", "").strip()
        if not text:
            continue

        speaker   = para.get("speaker")
        para_type = para.get("type", "narration")
        voice_id  = get_voice(speaker, voice_map, alias_map, narrator_voice) if use_voice_map else narrator_voice
        out_file  = output_dir / f"{i:04d}.mp3"

        if out_file.exists() and out_file.stat().st_size > 0:
            segments.append((out_file, para_type))
            continue

        label = f"({speaker})" if speaker else "(narrator)"
        print(f"  [{i+1}/{len(paragraphs)}] {label} {text[:60]}...")

        is_narrator = para_type != "dialogue"
        vs = narrator_voice_settings if (is_narrator and narrator_voice_settings) else None

        try:
            tts.synthesize(text=text, voice_id=voice_id, output_path=out_file,
                           voice_settings=vs)
            segments.append((out_file, para_type))
        except Exception as e:
            print(f"    ERROR: {e}")
            continue

        time.sleep(0.2)

    if not segments:
        print("No audio segments generated.")
        return None

    PAUSE = {
        ("narration", "narration"): 200,
        ("narration", "dialogue"):  400,
        ("dialogue",  "narration"): 300,
        ("dialogue",  "dialogue"):  150,
    }
    DEFAULT_PAUSE = 300

    print("\nMerging...")
    combined   = AudioSegment.empty()
    timestamps = []
    cursor_ms  = 0

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

    final_path = book_dir / "audio" / engine / f"chapter_{chapter_id:02d}.mp3"
    combined.export(str(final_path), format="mp3")

    # Save timestamps to JSON (backwards compat) + DB
    ts_path = book_dir / "audio" / engine / f"chapter_{chapter_id:02d}_timestamps.json"
    with open(ts_path, "w", encoding="utf-8") as f:
        json.dump(timestamps, f, indent=2)

    # Write ParagraphTimestamp to DB
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

    # Update chapter synth status
    db_chapter.audio_path   = str(final_path)
    db_chapter.synth_status = "done"
    db_chapter.synth_engine = engine
    db.commit()

    print(f"\nDone: {final_path}  ({len(combined)/1000:.1f}s)")
    return final_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("book",    nargs="?", default="alice", help="Name of the book")
    parser.add_argument("chapter", nargs="?", type=int, default=0, help="Chapter index")
    parser.add_argument("--engine", default="azure", choices=["azure", "elevenlabs", "xtts"])
    parser.add_argument("--assign",    action="store_true", help="Assign voices interactively before synthesis")
    parser.add_argument("--voice-map", action="store_true", help="Use saved voice map")
    parser.add_argument("--list-voices", action="store_true", help="Show available voices")
    parser.add_argument("--lang", default="en-US", help="Lang --list-voices (Azure)")
    args = parser.parse_args()

    tts = make_tts(args.engine)
    voices = tts.list_voices() if not hasattr(tts, 'list_voices') else (
        tts.list_voices(args.lang) if args.engine == "azure" else tts.list_voices()
    )

    if args.list_voices:
        print(f"\nVoices ({args.engine}):")
        print(f"  {'№':<5} {'ID':<35} {'Name':<25} {'Gender'}")
        print("  " + "-" * 75)
        for i, v in enumerate(voices):
            gender = v.get("gender", v.get("category", ""))
            print(f"  {i:<5} {v['id']:<35} {v['name']:<25} {gender}")
        return

    voice_map = load_voice_map(args.book, args.engine)

    if args.assign:
        book_dir = STORAGE_DIR / args.book
        gt_path = book_dir / "ground_truth.json"
        src_path = gt_path if gt_path.exists() else book_dir / "parsed_final.json"
        data = load_json(src_path)
        chapter = data["chapters"][args.chapter]
        speakers = get_chapter_speakers(chapter)

        print(f"\nCharacters in chapter [{args.chapter}] {chapter['title']}:")
        for s in speakers:
            current = voice_map.get(s, "—")
            print(f"  {s:<25} current: {current}")

        voice_map = assign_voices_interactively(speakers, voices, voice_map)
        save_voice_map(voice_map, args.book, args.engine)

    synthesize_chapter(
        args.book, args.chapter, args.engine,
        voice_map, use_voice_map=args.voice_map or args.assign
    )


if __name__ == "__main__":
    main()