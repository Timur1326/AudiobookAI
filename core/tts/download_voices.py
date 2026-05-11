"""
Downloads voice preview samples from ElevenLabs for all voices in voice_map_elevenlabs.json.
Saves them as MP3 files to storage/voices/ for use as XTTS reference audio,
and writes voice_map_xtts.json mapping character names to local file paths.
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
    """Download ElevenLabs voice previews for a book and build voice_map_xtts.json.

    Reads voice_map_elevenlabs.json to get the assigned voice IDs, fetches the
    preview MP3 for each unique voice from ElevenLabs, saves them to storage/voices/,
    then writes voice_map_xtts.json with {character: local_mp3_path} mappings.
    """
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

    # Download one MP3 per unique voice_id (named by voice_id)
    id_to_file: dict[str, Path] = {}
    for voice_id in set(voice_map.values()):
        out_path = VOICES_DIR / f"{voice_id}.mp3"
        id_to_file[voice_id] = out_path

        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"  {voice_id[:30]:<30} already exists")
            continue

        voice_meta = all_voices.get(voice_id)
        if not voice_meta:
            print(f"  {voice_id[:30]:<30} not found in ElevenLabs account")
            continue

        preview_url = voice_meta.get("preview_url")
        if not preview_url:
            print(f"  {voice_id[:30]:<30} no preview_url")
            continue

        print(f"  {voice_meta['name']:<30} downloading ...", end=" ", flush=True)
        audio = requests.get(preview_url)
        audio.raise_for_status()
        out_path.write_bytes(audio.content)
        print(f"saved {out_path.name}")

    print(f"\nDone. Files in {VOICES_DIR}:")
    for f in sorted(VOICES_DIR.iterdir()):
        size_kb = f.stat().st_size // 1024
        print(f"  {f.name:<45} {size_kb} KB")

    # Build voice_map_xtts.json — all characters, including duplicates
    xtts_map = {}
    for character, voice_id in voice_map.items():
        mp3 = id_to_file.get(voice_id)
        if mp3 and mp3.exists():
            xtts_map[character] = str(mp3)

    xtts_map_path = Path(f"storage/uploads/{book}/voice_map_xtts.json")
    with open(xtts_map_path, "w", encoding="utf-8") as f:
        json.dump(xtts_map, f, ensure_ascii=False, indent=2)
    print(f"\nvoice_map_xtts.json saved: {xtts_map_path}")


if __name__ == "__main__":
    book = sys.argv[1] if len(sys.argv) > 1 else "alice"
    download_voices(book)