"""
Generates sound effects using ElevenLabs Sound Effects API based on scene_sound_query

Reading from parsed_scenes.json and writing results to parsed_scenes_with_sounds.json.

Launch:
    python -m core.audio.sound_generator alice
    python -m core.audio.sound_generator alice --chapter 7
    python -m core.audio.sound_generator alice --input parsed_scenes.json
"""

import hashlib
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs import ElevenLabs

load_dotenv()

SOUNDS_DIR = Path("storage/sounds/elevenlabs")
DURATION_SECONDS = 10
PROMPT_INFLUENCE = 0.3
REQUEST_DELAY = 1.0


def query_to_filename(query: str) -> str:
    md5 = hashlib.md5(query.encode("utf-8")).hexdigest()
    return f"{md5}.mp3"


def generate_sound(client: ElevenLabs, query: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    result = client.text_to_sound_effects.convert(
        text=query,
        duration_seconds=DURATION_SECONDS,
        prompt_influence=PROMPT_INFLUENCE,
    )
    with open(path, "wb") as f:
        for chunk in result:
            f.write(chunk)


def collect_queries(data: dict, chapter_id: int | None) -> list[str]:
    seen: set[str] = set()
    for ch in data["chapters"]:
        if chapter_id is not None and ch["id"] != chapter_id:
            continue
        for p in ch["paragraphs"]:
            q = p.get("scene_sound_query")
            if q:
                seen.add(q)
    return sorted(seen)


def run(
    book: str,
    chapter_id: int | None = None,
    input_file: str = "parsed_scenes.json",
    output_file: str = "parsed_scenes_with_sounds.json",
) -> None:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY не задан в .env")

    client = ElevenLabs(api_key=api_key)

    base = Path(f"storage/uploads/{book}")
    input_path  = base / input_file
    output_path = base / output_file

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    queries = collect_queries(data, chapter_id)
    total = len(queries)

    scope = f"Chapter id={chapter_id}" if chapter_id is not None else "all chapters"
    print(f"Book:  {data['title']}")
    # print(f" =:  {scope}")
    # print(f" query: {total}\n")

    generated = 0
    from_cache = 0

    query_to_path: dict[str, Path] = {}

    for i, query in enumerate(queries, 1):
        filename = query_to_filename(query)
        sound_path = SOUNDS_DIR / filename

        if sound_path.exists() and sound_path.stat().st_size > 0:
            print(f" Cache:       {query}  ({i}/{total})")
            from_cache += 1
        else:
            print(f"  Generate: {query}  ({i}/{total})")
            try:
                generate_sound(client, query, sound_path)
                generated += 1
            except Exception as e:
                print(f"    ERROR: {e}")
                sound_path = None

            if i < total:
                time.sleep(REQUEST_DELAY)

        if sound_path is not None:
            query_to_path[query] = sound_path

    for ch in data["chapters"]:
        if chapter_id is not None and ch["id"] != chapter_id:
            for p in ch["paragraphs"]:
                if "scene_sound_file" not in p:
                    p["scene_sound_file"] = None
            continue

        for p in ch["paragraphs"]:
            q = p.get("scene_sound_query")
            if q and q in query_to_path:
                p["scene_sound_file"] = str(query_to_path[q])
            else:
                p["scene_sound_file"] = None

    tmp = str(output_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=True, indent=2))
    os.replace(tmp, output_path)

    print(f"\n{'='*50}")
    print(f"Generated: {generated}")
    print(f"From cache:       {from_cache}")
    print(f"Total:         {total}")
    print(f"Saved:     {output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("book",      help="Name of book: alice")
    parser.add_argument("--chapter", type=int, default=None,
                        help="chapter_id")
    parser.add_argument("--input",   default="parsed_scenes.json")
    parser.add_argument("--output",  default="parsed_scenes_with_sounds.json")
    args = parser.parse_args()

    run(
        book=args.book,
        chapter_id=args.chapter,
        input_file=args.input,
        output_file=args.output,
    )