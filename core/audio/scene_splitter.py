"""
Scene splitter: divides each chapter into scenes using LLM.
Adds `scene_id` to every paragraph and a `scenes` list to every chapter.

Usage:
    python -m core.audio.scene_splitter alice
    python -m core.audio.scene_splitter alice --chapter 0
    python -m core.audio.scene_splitter alice --preview
"""

import json
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are a literary analyst for an audiobook production.
Your task: divide a chapter into scenes based on LOCATION changes.

A scene is a continuous section of text that takes place in the same location.
Change scene only when characters clearly move to a different physical place.

For each scene return:
- scene_id: integer starting from 0
- name: short scene name (2-4 words)
- location: ambient sound description of the place (2-5 words, English).
    Think: what would a microphone placed here record?
    via location i will generate ambient sounds, so be specific about the place and time of day if relevant 
- start_paragraph: index of first paragraph (inclusive)
- end_paragraph: index of last paragraph (inclusive)

Rules:
- Cover ALL paragraphs from 0 to the last index
- No gaps between scenes (end of scene N + 1 = start of scene N+1)


Return ONLY a valid JSON array, no explanation.
"""


def build_prompt(paragraphs: list[dict]) -> str:
    lines = []
    for i, p in enumerate(paragraphs):
        lines.append(f"[{i}] ({p.get('type', 'narration')}) {p['text'][:150]}")

    return f"""\
Divide this chapter into scenes (paragraphs 0–{len(paragraphs) - 1}).

Return JSON array:
[
  {{
    "scene_id": 0,
    "name": "Riverbank",
    "location": "outdoor riverbank summer",
    "start_paragraph": 0,
    "end_paragraph": 24
  }},
  ...
]

PARAGRAPHS:
{chr(10).join(lines)}
"""


def call_llm(client: anthropic.Anthropic, paragraphs: list[dict]) -> list[dict]:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(paragraphs)}],
    )
    raw = response.content[0].text

    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array in response:\n{raw}")

    scenes = json.loads(match.group())

    # Re-assign scene_id by order in case LLM returned wrong ids
    for i, s in enumerate(scenes):
        s["scene_id"] = i

    return scenes


def build_scenes_with_paragraphs(paragraphs: list[dict], scenes: list[dict]) -> list[dict]:
    """Group paragraphs into scenes. Returns list of scene dicts with nested paragraphs."""
    result = []
    for scene in scenes:
        start = scene["start_paragraph"]
        end = min(scene["end_paragraph"], len(paragraphs) - 1)
        scene_paragraphs = []
        for p in paragraphs[start:end + 1]:
            # Drop scene_id field if it was previously added
            clean = {k: v for k, v in p.items() if k != "scene_id"}
            scene_paragraphs.append(clean)
        result.append({
            "scene_id":  scene["scene_id"],
            "name":      scene["name"],
            "location":  scene["location"],
            "paragraphs": scene_paragraphs,
        })

    # Assign any leftover paragraphs to the last scene
    if scenes:
        last_end = scenes[-1]["end_paragraph"]
        if last_end < len(paragraphs) - 1:
            for p in paragraphs[last_end + 1:]:
                clean = {k: v for k, v in p.items() if k != "scene_id"}
                result[-1]["paragraphs"].append(clean)

    return result


def run(
    book: str,
    chapter_id: int | None = None,
    input_file: str = "parsed_final.json",
    output_file: str = "parsed_with_scenes.json",
    preview: bool = False,
) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    client = anthropic.Anthropic(api_key=api_key)

    base = Path(f"storage/uploads/{book}")
    input_path = base / input_file
    output_path = base / output_file

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    chapters = data["chapters"]
    target = [c for c in chapters if chapter_id is None or c["id"] == chapter_id]

    print(f"Book:   {data['title']}")
    print(f"Model:  {MODEL}")
    print(f"Mode:   {'PREVIEW' if preview else 'WRITE'}\n")

    for ch in target:
        paragraphs = ch["paragraphs"]
        print(f"[{ch['id']}] {ch['title'][:60]}  ({len(paragraphs)} paragraphs)")

        scenes = call_llm(client, paragraphs)

        print(f"  Scenes found: {len(scenes)}")
        print(f"  {'#':<4} {'Name':<25} {'Location':<30} {'Paragraphs'}")
        print("  " + "-" * 75)
        for s in scenes:
            rng = f"{s['start_paragraph']}–{s['end_paragraph']}"
            print(f"  {s['scene_id']:<4} {s['name']:<25} {s['location']:<30} {rng}")

        if not preview:
            ch["scenes"] = build_scenes_with_paragraphs(paragraphs, scenes)
            del ch["paragraphs"]
            ch["total_paragraphs"] = sum(len(s["paragraphs"]) for s in ch["scenes"])

        print()

    if preview:
        print("Preview done. Run without --preview to save.")
        return

    tmp = str(output_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=True, indent=2))
    os.replace(tmp, output_path)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("book", help="Book name, e.g.: alice")
    parser.add_argument("--chapter", type=int, default=None, help="chapter id (from JSON)")
    parser.add_argument("--input",   default="ground_truth_fixed.json")
    parser.add_argument("--output",  default="parsed_with_scenes.json")
    parser.add_argument("--preview", action="store_true", help="Show scenes without saving")
    args = parser.parse_args()

    run(
        book=args.book,
        chapter_id=args.chapter,
        input_file=args.input,
        output_file=args.output,
        preview=args.preview,
    )