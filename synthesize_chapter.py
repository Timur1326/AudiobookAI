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
import time
from pathlib import Path

from dotenv import load_dotenv
from pydub import AudioSegment

load_dotenv()

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



def get_voice(speaker: str | None, voice_map: dict, narrator_voice: str) -> str:
    if speaker and speaker.strip() in voice_map:
        return voice_map[speaker.strip()]
    return voice_map.get("NARRATOR", narrator_voice)


def synthesize_chapter(
    book: str,
    chapter_idx: int,
    engine: str,
    voice_map: dict,
    use_voice_map: bool,
) -> Path:
    tts = make_tts(engine)
    narrator_voice = default_voice(engine)

    book_dir = STORAGE_DIR / book
    gt_path = book_dir / "ground_truth_fixed.json"
    src_path = gt_path if gt_path.exists() else book_dir / "parsed_final.json"
    data = load_json(src_path)

    chapters = data["chapters"]
    if chapter_idx >= len(chapters):
        raise ValueError(f"Chapter {chapter_idx} no exist (all {len(chapters)})")

    chapter = chapters[chapter_idx]
    paragraphs = chapter["paragraphs"]

    print(f"\nBook:    {data['title']}")
    print(f"Chapter:    [{chapter['id']}] {chapter['title']}")
    print(f"Engine:   {engine}")
    print(f"Voices:   {'per character' if use_voice_map else 'one narrator voice'}")
    print(f"Paragraphs: {len(paragraphs)}")

    output_dir = book_dir / "audio" / engine / f"chapter_{chapter['id']:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)

    segments: list[tuple[Path, str]] = []  # (path, para_type)

    for i, para in enumerate(paragraphs):
        text = para.get("text", "").strip()
        if not text:
            continue

        speaker = para.get("speaker_ground_truth") or para.get("speaker")
        voice_id = get_voice(speaker, voice_map, narrator_voice) if use_voice_map else narrator_voice
        out_file = output_dir / f"{i:04d}.mp3"
        para_type = para.get("type", "narration")

        if out_file.exists() and out_file.stat().st_size > 0:
            print(f"  [{i+1}/{len(paragraphs)}] skip")
            segments.append((out_file, para_type))
            continue

        label = f"({speaker})" if speaker else "(narrator)"
        print(f"  [{i+1}/{len(paragraphs)}] {label} {text[:60]}...")

        try:
            tts.synthesize(text=text, voice_id=voice_id, output_path=out_file)
            segments.append((out_file, para_type))
        except Exception as e:
            print(f"    ERROR: {e}")
            continue

        time.sleep(0.2)

    if not segments:
        print("No audio segments were generated.")
        return None

    # Pause durations depending on paragraph type transitions
    PAUSE = {
        ("narration",  "narration"):  200,
        ("narration",  "dialogue"):   400,
        ("dialogue",   "narration"):  300,
        ("dialogue",   "dialogue"):   150,
    }
    DEFAULT_PAUSE = 300

    print("\nMerging audio files...")
    combined = AudioSegment.empty()
    for idx, (seg, curr_type) in enumerate(segments):
        combined += AudioSegment.from_mp3(seg)
        if idx < len(segments) - 1:
            next_type = segments[idx + 1][1]
            pause_ms = PAUSE.get((curr_type, next_type), DEFAULT_PAUSE)
            combined += AudioSegment.silent(duration=pause_ms)

    final_path = book_dir / "audio" / engine / f"chapter_{chapter['id']:02d}.mp3"
    combined.export(str(final_path), format="mp3")
    print(f"\nГотово: {final_path}  ({len(combined)/1000:.1f} сек)")
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