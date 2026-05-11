"""
LLM dialogue attribution with character context.

Processes paragraphs in chunks of CHUNK_SIZE, sending each chunk to Haiku
with the full list of known characters as context. Updates Paragraph.speaker
directly in the DB.
"""

import json
import os
import re
import time
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"
CHUNK_SIZE = 20   # paragraphs per LLM call — balances context quality vs token cost
RETRY_LIMIT = 3

# Characters list is injected at runtime so the LLM prefers canonical names from the DB.
SYSTEM_PROMPT_TEMPLATE = """\
You are an expert literary analyst specializing in dialogue attribution.
You will receive numbered paragraphs from a novel.

Known characters in this book: {characters}

Your task: for EVERY paragraph return its index and type.
For DIALOGUE paragraphs also identify the speaker.

Rules:
- Prefer names from the known characters list when they match the context
- Use character name exactly as it appears in text
- If speaker cannot be determined, return null
- Return ONLY valid JSON, no explanation

Output format:
[
  {{"index": 0, "type": "narration", "speaker": null}},
  {{"index": 1, "type": "dialogue", "speaker": "Alice"}},
  ...
]
"""


def _build_system_prompt(characters: list[str]) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(characters=", ".join(characters))


def _build_user_message(chunk: list[dict[str, Any]], offset: int) -> str:
    """Format a chunk of paragraphs as numbered lines for the LLM."""
    lines = []
    for i, para in enumerate(chunk):
        idx = offset + i
        lines.append(f"[{idx}] ({para['type']}) {para['text']}")
    return "\n\n".join(lines)


def _parse_response(content: str) -> dict[int, str | None]:
    """Extract {paragraph_index: speaker} mapping from raw LLM JSON response."""
    match = re.search(r"\[.*\]", content, re.DOTALL)
    if not match:
        raise ValueError("JSON-array not found in response")
    items = json.loads(match.group())
    return {item["index"]: item.get("speaker") for item in items}


def attribute_chunk(
    client: anthropic.Anthropic,
    chunk: list[dict[str, Any]],
    offset: int,
    system_prompt: str,
) -> dict[int, str | None]:
    """Send one chunk of paragraphs to the LLM and return {index: speaker} mapping.

    Retries up to RETRY_LIMIT times on JSON parse errors.
    On rate limit errors, backs off with increasing wait times.
    Returns empty attribution (all None) if all retries fail.
    """
    user_msg = _build_user_message(chunk, offset)

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
            )
            return _parse_response(response.content[0].text)

        except (ValueError, json.JSONDecodeError) as e:
            print(f"    [attempt {attempt}/{RETRY_LIMIT}] invalid JSON: {e}")
            if attempt == RETRY_LIMIT:
                print("    Skipping chunk due to repeated parsing errors.")
                return {offset + i: None for i, p in enumerate(chunk) if p["type"] == "dialogue"}
            time.sleep(1)

        except (anthropic.RateLimitError, anthropic.OverloadedError) as e:
            wait = 15 * attempt
            print(f"    {type(e).__name__} — waiting {wait}s...")
            time.sleep(wait)

    return {}


def _attribute_paragraphs(
    client: anthropic.Anthropic,
    db_paras: list,
    system_prompt: str,
    max_scene_size: int,
) -> int:
    """Process all paragraphs in chunks, writing speaker back to each DB object.

    Returns the number of speakers attributed.
    """
    para_dicts = [{"text": p.text, "type": p.type} for p in db_paras]
    total = 0

    for chunk_start in range(0, len(db_paras), max_scene_size):
        chunk    = para_dicts[chunk_start: chunk_start + max_scene_size]
        db_chunk = db_paras[chunk_start: chunk_start + max_scene_size]
        attributions = attribute_chunk(client, chunk, offset=chunk_start,
                                       system_prompt=system_prompt)
        for idx, speaker in attributions.items():
            local_idx = idx - chunk_start
            if 0 <= local_idx < len(db_chunk) and speaker:
                db_chunk[local_idx].speaker = speaker
                total += 1

    return total


def _load_characters_from_db(book_id: int, db) -> list[str]:
    """Load canonical names + all aliases for every character in the book."""
    from backend.models import Character as DBCharacter
    chars = db.query(DBCharacter).filter(DBCharacter.book_id == book_id).all()
    characters = []
    for c in chars:
        characters.append(c.name)
        for alias in c.aliases:
            if alias.alias not in characters:
                characters.append(alias.alias)
    return characters


def run_on_db(book_id: int, db, chapter_id: int | None = None,
              max_scene_size: int = CHUNK_SIZE) -> None:
    """Run dialogue attribution directly on DB paragraphs, updating Paragraph.speaker.

    Processes paragraphs scene by scene when scenes exist, or falls back to
    chapter-level processing if scene detection has not been run yet.
    """
    from backend.models import (
        Chapter as DBChapter,
        Paragraph as DBParagraph,
        Scene as DBScene,
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    client = anthropic.Anthropic(api_key=api_key)

    characters = _load_characters_from_db(book_id, db)
    print(f"Known characters: {len(characters)}  —  {', '.join(characters) or 'none yet'}")
    system_prompt = _build_system_prompt(characters)

    chapters_q = db.query(DBChapter).filter(DBChapter.book_id == book_id)
    if chapter_id is not None:
        chapters_q = chapters_q.filter(DBChapter.chapter_id == chapter_id)
    chapters = chapters_q.order_by(DBChapter.chapter_index).all()

    total_attributed = 0

    for ch in chapters:
        print(f"\n[{ch.chapter_id}] {ch.title}")

        scenes = (db.query(DBScene)
                    .filter(DBScene.chapter_id == ch.id)
                    .order_by(DBScene.scene_index)
                    .all())

        if scenes:
            for scene in scenes:
                db_paras = (db.query(DBParagraph)
                              .filter(DBParagraph.scene_id == scene.id)
                              .order_by(DBParagraph.index)
                              .all())

                dialogue_count = sum(1 for p in db_paras if p.type == "dialogue")
                if dialogue_count == 0:
                    continue

                print(f"  Scene {scene.scene_index}  ({len(db_paras)} paras, {dialogue_count} dialogues)")
                total_attributed += _attribute_paragraphs(client, db_paras, system_prompt, max_scene_size)
                time.sleep(0.3)
        else:
            # No scenes — process whole chapter as one block
            db_paras = (db.query(DBParagraph)
                          .filter(DBParagraph.chapter_id == ch.id)
                          .order_by(DBParagraph.index)
                          .all())
            total_attributed += _attribute_paragraphs(client, db_paras, system_prompt, max_scene_size)

    db.commit()
    print(f"\nAttribution done. Total attributed: {total_attributed}")