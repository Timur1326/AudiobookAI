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
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"  # needs reasoning about the whole book


SYSTEM_PROMPT = """\
You are a literary analyst. Your task is to extract ALL speaking characters from a novel.

For each character return:
- name: the most common form of their name as it appears in the text
- gender: "male" / "female" / "unknown"
- age: "child" / "young_adult" / "middle_aged" / "old" / "unknown"
- personality: 2-4 adjectives describing their character (e.g. "curious, brave, impulsive")
- accent: best guess at accent/nationality based on context (e.g. "british", "american", "unknown")
- voice_description: 1-2 sentences describing what their voice should sound like for an audiobook

Rules:
- Include EVERY character who has dialogue lines — do not skip any
- One entry per character — use the most common name from the speaker list
- Do NOT merge names or assign aliases
- Ignore speaker names that are clearly automated attribution errors (common words, verb fragments)
- Do NOT include narrators or unnamed crowd characters

Return ONLY valid JSON array, no explanation:
[
  {
    "name": "Alice",
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

    for attempt in range(5):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except anthropic.OverloadedError:
            wait = 15 * (2 ** attempt)
            print(f"API overloaded, retrying in {wait}s (attempt {attempt + 1}/5)...")
            time.sleep(wait)
    else:
        raise RuntimeError("API overloaded after 5 retries")

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


def build_prompt_from_db(book_id: int, db) -> str:
    """Build LLM prompt using dialogue paragraphs from DB."""
    from collections import Counter
    from backend.models import Paragraph as DBParagraph, Chapter as DBChapter, Book as DBBook

    db_book = db.query(DBBook).filter(DBBook.id == book_id).first()
    title  = db_book.title  if db_book else "Unknown"
    author = db_book.author if db_book else "Unknown"

    rows = (db.query(DBParagraph)
              .join(DBChapter)
              .filter(DBChapter.book_id == book_id,
                      DBParagraph.type == "dialogue",
                      DBParagraph.speaker.isnot(None))
              .all())

    # Count frequency of each speaker name
    freq: Counter = Counter(p.speaker for p in rows)

    # Filter: keep only speakers that appear 2+ times and look like proper names
    # (capitalized, 3+ chars, not purely lowercase common words)
    valid_speakers = {
        name for name, count in freq.items()
        if count >= 2 and len(name) >= 3 and name[0].isupper()
    }

    samples: dict[str, list[str]] = {}
    for p in rows:
        if p.speaker not in valid_speakers:
            continue
        if p.speaker not in samples:
            samples[p.speaker] = []
        if len(samples[p.speaker]) < 3:
            samples[p.speaker].append(p.text[:120])

    lines = [f"Book: {title} by {author}\n", "Speaking characters with sample dialogue:\n"]
    for speaker, quotes in sorted(samples.items()):
        lines.append(f"{speaker}:")
        for q in quotes:
            lines.append(f'  "{q}"')

    return "\n".join(lines)


def run_on_db(book_id: int, db) -> None:
    """
    Extract characters from DB paragraphs and save directly to DB.
    Creates Character + CharacterAlias records.
    """
    from backend.models import Character as DBCharacter

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    client = anthropic.Anthropic(api_key=api_key)

    # Build prompt from DB data
    prompt = build_prompt_from_db(book_id, db)

    print(f"Extracting characters via LLM...")
    # Reuse call_llm by passing a fake data dict structure
    # Actually call the API directly since we already have the prompt
    for attempt in range(5):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except anthropic.OverloadedError:
            wait = 15 * (2 ** attempt)
            print(f"API overloaded, retrying in {wait}s...")
            time.sleep(wait)
    else:
        raise RuntimeError("API overloaded after 5 retries")

    raw = response.content[0].text
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array in response:\n{raw}")
    characters = json.loads(match.group())

    print(f"Found {len(characters)} characters")

    # Clear existing characters and their aliases for this book
    # (bulk delete bypasses ORM cascade, so delete aliases explicitly first)
    from backend.models import CharacterAlias
    char_ids = [c.id for c in db.query(DBCharacter.id).filter(DBCharacter.book_id == book_id).all()]
    if char_ids:
        db.query(CharacterAlias).filter(CharacterAlias.character_id.in_(char_ids)).delete(synchronize_session=False)
    db.query(DBCharacter).filter(DBCharacter.book_id == book_id).delete()
    db.flush()

    for c in characters:
        name = c.get("name", "").strip()
        if not name:
            continue

        db_char = DBCharacter(
            book_id=book_id,
            name=name,
            gender=c.get("gender"),
            age=c.get("age"),
            personality=c.get("personality"),
            accent=c.get("accent"),
            voice_desc=c.get("voice_description"),
        )
        db.add(db_char)
        db.flush()

    db.commit()
    print(f"Saved {len(characters)} characters to DB.")


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