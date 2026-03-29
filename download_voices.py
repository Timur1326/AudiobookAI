"""
Downloads voice preview samples from ElevenLabs for all voices in voice_map_elevenlabs.json.
Saves them as WAV files to storage/voices/ for use as XTTS reference audio.

Usage:
    python download_voices.py alice
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

VOICES_DIR = Path("storage/voices")


def download_voices(book: str) -> None:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY not set in .env")

    vm_path = Path(f"storage/uploads/{book}/voice_map_elevenlabs.json")
    if not vm_path.exists():
        raise FileNotFoundError(f"Voice map not found: {vm_path}")

    with open(vm_path, encoding="utf-8") as f:
        voice_map = json.load(f)

    VOICES_DIR.mkdir(parents=True, exist_ok=True)

    # Fetch all voices metadata from ElevenLabs once
    headers = {"xi-api-key": api_key}
    resp = requests.get("https://api.elevenlabs.io/v1/voices", headers=headers)
    resp.raise_for_status()
    all_voices = {v["voice_id"]: v for v in resp.json()["voices"]}

    seen_ids: set[str] = set()

    for character, voice_id in voice_map.items():
        if voice_id in seen_ids:
            print(f"  {character:<20} skipped (same voice as previous)")
            continue
        seen_ids.add(voice_id)

        out_path = VOICES_DIR / f"{character.lower().replace(' ', '_')}.mp3"

        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"  {character:<20} already exists: {out_path.name}")
            continue

        voice_meta = all_voices.get(voice_id)
        if not voice_meta:
            print(f"  {character:<20} voice_id {voice_id} not found in your ElevenLabs account")
            continue

        preview_url = voice_meta.get("preview_url")
        if not preview_url:
            print(f"  {character:<20} no preview_url available")
            continue

        print(f"  {character:<20} downloading {voice_meta['name']} ...", end=" ", flush=True)
        audio = requests.get(preview_url)
        audio.raise_for_status()
        out_path.write_bytes(audio.content)
        print(f"saved {out_path.name}")

    print(f"\nDone. Files in {VOICES_DIR}:")
    for f in sorted(VOICES_DIR.iterdir()):
        size_kb = f.stat().st_size // 1024
        print(f"  {f.name:<35} {size_kb} KB")

    # Build voice_map_xtts.json
    xtts_map = {}
    for character, voice_id in voice_map.items():
        mp3 = VOICES_DIR / f"{character.lower().replace(' ', '_')}.mp3"
        if mp3.exists():
            xtts_map[character] = str(mp3)

    xtts_map_path = Path(f"storage/uploads/{book}/voice_map_xtts.json")
    with open(xtts_map_path, "w", encoding="utf-8") as f:
        json.dump(xtts_map, f, ensure_ascii=False, indent=2)
    print(f"\nvoice_map_xtts.json saved: {xtts_map_path}")


if __name__ == "__main__":
    book = sys.argv[1] if len(sys.argv) > 1 else "alice"
    download_voices(book)