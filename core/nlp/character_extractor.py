"""
Character extractor: analyzes the book text and returns a list of characters
with their descriptions (age, gender, personality, accent/nationality).

Output saved to storage/uploads/{book}/characters.json

Usage:
    python -m core.nlp.character_extractor alice
    python -m core.nlp.character_extractor alice --input parsed_with_scenes.json
    python -m core.nlp.character_extractor alice --preview
"""

import json
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"  # needs reasoning about the whole book


SYSTEM_PROMPT = """\
You are a literary analyst. Your task is to extract all speaking characters from a novel.

For each character return:
- name: the most common form of their name as it appears in the text
- aliases: other names/titles used for this character (e.g. ["the White Rabbit", "Rabbit"])
- gender: "male" / "female" / "unknown"
- age: "child" / "young_adult" / "middle_aged" / "old" / "unknown"
- personality: 2-4 adjectives describing their character (e.g. "curious, brave, impulsive")
- accent: best guess at accent/nationality based on context (e.g. "british", "american", "unknown")
- voice_description: 1-2 sentences describing what their voice should sound like for an audiobook

Only include characters who actually speak (have dialogue lines).
Exclude narrators and unnamed background characters.

Return ONLY valid JSON array, no explanation:
[
  {
    "name": "Alice",
    "aliases": [],
    "gender": "female",
    "age": "child",
    "personality": "curious, brave, imaginative, polite",
    "accent": "british",
    "voice_description": "A young girl's voice, bright and curious, slightly formal for her age."
  }
]
"""


def build_prompt(data: dict) -> str:
    # Collect dialogue samples per speaker (max 3 lines each)
    samples: dict[str, list[str]] = {}
    for chapter in data["chapters"]:
        paragraphs = chapter.get("paragraphs") or []
        for p in paragraphs:
            if p.get("type") != "dialogue":
                continue
            speaker = p.get("speaker_ground_truth") or p.get("speaker")
            if not speaker:
                continue
            if speaker not in samples:
                samples[speaker] = []
            if len(samples[speaker]) < 3:
                samples[speaker].append(p["text"][:120])

    lines = [f"Book: {data['title']} by {data['author']}\n"]
    lines.append("Speaking characters with sample dialogue:\n")
    for speaker, quotes in sorted(samples.items()):
        lines.append(f"{speaker}:")
        for q in quotes:
            lines.append(f'  "{q}"')

    return "\n".join(lines)


def call_llm(client: anthropic.Anthropic, data: dict) -> list[dict]:
    prompt = build_prompt(data)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text

    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array in response:\n{raw}")

    try:
        return json.loads(match.group())
    except json.JSONDecodeError as e:
        print(f"\nRaw response:\n{raw}\n")
        raise ValueError(f"Invalid JSON from LLM: {e}") from e


def run(
    book: str,
    input_file: str = "parsed_with_scenes.json",
    output_file: str = "characters.json",
    preview: bool = False,
) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    client = anthropic.Anthropic(api_key=api_key)

    base = Path(f"storage/uploads/{book}")
    input_path = base / input_file

    # Fallback to parsed_final.json if input not found
    if not input_path.exists():
        input_path = base / "parsed_final.json"

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    print(f"Book:   {data['title']}")
    print(f"Model:  {MODEL}")
    print(f"Input:  {input_path.name}\n")

    print("Extracting characters...")
    characters = call_llm(client, data)

    print(f"\nFound {len(characters)} characters:\n")
    print(f"  {'Name':<20} {'Gender':<10} {'Age':<14} {'Personality'}")
    print("  " + "-" * 75)
    for c in characters:
        print(f"  {c['name']:<20} {c['gender']:<10} {c['age']:<14} {c['personality']}")

    if preview:
        print("\nPreview done. Run without --preview to save.")
        return

    output_path = base / output_file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(characters, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("book", help="Book name")
    parser.add_argument("--input",   default="parsed_with_scenes.json")
    parser.add_argument("--output",  default="characters.json")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()

    run(
        book=args.book,
        input_file=args.input,
        output_file=args.output,
        preview=args.preview,
    )