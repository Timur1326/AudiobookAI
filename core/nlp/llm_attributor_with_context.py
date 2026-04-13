"""
LLM attribution with character context.

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
CHUNK_SIZE = 20
RETRY_LIMIT = 3

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


def extract_characters(data: dict) -> list[str]:
    seen: set[str] = set()
    for chapter in data["chapters"]:
        # Support both flat paragraphs and nested scenes
        if "paragraphs" in chapter:
            paragraphs = chapter["paragraphs"]
        else:
            paragraphs = [p for s in chapter.get("scenes", []) for p in s["paragraphs"]]
        for para in paragraphs:
            speaker = para.get("speaker")
            if speaker and speaker.strip():
                seen.add(speaker.strip())
    return sorted(seen)


def _iter_scenes(chapter: dict):
    """Yield (scene_label, paragraphs_list) for each scene or the whole chapter."""
    if "scenes" in chapter:
        for scene in chapter["scenes"]:
            yield scene.get("name", "scene"), scene["paragraphs"]
    else:
        yield chapter["title"], chapter["paragraphs"]


def _build_system_prompt(characters: list[str]) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(characters=", ".join(characters))


def _build_user_message(chunk: list[dict[str, Any]], offset: int) -> str:
    lines = []
    for i, para in enumerate(chunk):
        idx = offset + i
        lines.append(f"[{idx}] ({para['type']}) {para['text']}")
    return "\n\n".join(lines)


def _parse_response(content: str) -> dict[int, str | None]:
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
    user_msg = _build_user_message(chunk, offset)

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = response.content[0].text
            return _parse_response(raw)

        except (ValueError, json.JSONDecodeError) as e:
            print(f"    [attempt {attempt}/{RETRY_LIMIT}] dont valid JSON: {e}")
            if attempt == RETRY_LIMIT:
                print("    Skip this chunk due to repeated parsing errors.")
                return {
                    offset + i: None
                    for i, p in enumerate(chunk)
                    if p["type"] == "dialogue"
                }
            time.sleep(1)

        except (anthropic.RateLimitError, anthropic.OverloadedError) as e:
            wait = 15 * attempt
            print(f"    {type(e).__name__} — waiting {wait}s...")
            time.sleep(wait)

    return {}


def _compare(label: str, dialogue_indices: list[int], paragraphs: list[dict],
             field_a: str, label_a: str, field_b: str, label_b: str) -> None:
    both = [
        i for i in dialogue_indices
        if paragraphs[i].get(field_a) is not None
        and paragraphs[i].get(field_b) is not None
    ]
    if not both:
        print(f"{label_a} vs {label_b}: no metrics for comparison")
        return

    match = sum(
        1 for i in both
        if paragraphs[i][field_a].strip().lower()
        == paragraphs[i][field_b].strip().lower()
    )
    print(f"\n{label_a} vs {label_b}:")
    print(f"  Both gave response:  {len(both)}")
    print(f"  Matches:      {match}  ({match / len(both) * 100:.1f}%)")
    print(f"  Discrepancies:     {len(both) - match}")

    shown = 0
    for i in both:
        if paragraphs[i][field_a].strip().lower() != paragraphs[i][field_b].strip().lower():
            print(f"  [{i}] {label_a}={paragraphs[i][field_a]!r:20}  {label_b}={paragraphs[i][field_b]!r}")
            print(f"       {paragraphs[i]['text'][:80]}...")
            shown += 1
            if shown >= 5:
                break


def run_with_context(
    input_path: str,
    zeroshot_path: str,
    output_path: str,
    chapter_idx: int = 0,
    chunk_size: int = CHUNK_SIZE,
) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not entered in .env")

    client = anthropic.Anthropic(api_key=api_key)

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    # Загружаем zero-shot результаты если есть
    zeroshot_paragraphs: dict[int, str | None] = {}
    if os.path.exists(zeroshot_path):
        with open(zeroshot_path, encoding="utf-8") as f:
            zs_data = json.load(f)
        zs_paras = zs_data["chapters"][chapter_idx]["paragraphs"]
        zeroshot_paragraphs = {
            i: p.get("speaker_llm_zeroshot")
            for i, p in enumerate(zs_paras)
        }
        print(f"Zero-shot data is loaded: {zeroshot_path}")
    else:
        print(f"Zero-shot not found file ({zeroshot_path}) ")

    characters = extract_characters(data)
    print(f"\nCharacters extracted: {len(characters)}")
    print(f"  {', '.join(characters)}\n")

    system_prompt = _build_system_prompt(characters)

    chapter = data["chapters"][chapter_idx]
    paragraphs = chapter["paragraphs"]
    total = len(paragraphs)

    print(f"Chapter [{chapter_idx}]: {chapter['title']}")
    print(f"Paragraphs: {total}  |  chunks: {(total + chunk_size - 1) // chunk_size}")
    print(f"Model: {MODEL}\n")

    for i, p in enumerate(paragraphs):
        p["speaker_llm_context"] = None
        if zeroshot_paragraphs:
            p["speaker_llm_zeroshot"] = zeroshot_paragraphs.get(i)

    dialogue_indices = [i for i, p in enumerate(paragraphs) if p["type"] == "dialogue"]
    print(f"Dialogue paragraphs: {len(dialogue_indices)}\n")

    for chunk_start in range(0, total, chunk_size):
        chunk = paragraphs[chunk_start: chunk_start + chunk_size]
        chunk_num = chunk_start // chunk_size + 1
        total_chunks = (total + chunk_size - 1) // chunk_size

        print(f"Chunk {chunk_num}/{total_chunks}  (paragraphs {chunk_start}–{chunk_start + len(chunk) - 1})")

        attributions = attribute_chunk(client, chunk, offset=chunk_start, system_prompt=system_prompt)

        for idx, speaker in attributions.items():
            paragraphs[idx]["speaker_llm_context"] = speaker

        attributed = sum(1 for v in attributions.values() if v is not None)
        print(f"  attributed {attributed}/{len(attributions)} replies")

        if chunk_start + chunk_size < total:
            time.sleep(0.5)

    print("\n" + "=" * 50)
    print("STATISTICS:")
    print("=" * 50)

    total_dialogue = len(dialogue_indices)
    ctx_attributed = sum(
        1 for i in dialogue_indices if paragraphs[i]["speaker_llm_context"] is not None
    )
    booknlp_attributed = sum(
        1 for i in dialogue_indices if paragraphs[i].get("speaker") is not None
    )

    print(f"Total dialogue:                  {total_dialogue}")
    print(f"BookNLP attributed:           {booknlp_attributed}")
    print(f"LLM with-context attributed:  {ctx_attributed}")

    _compare("", dialogue_indices, paragraphs,
             "speaker", "BookNLP",
             "speaker_llm_context", "LLM-context")

    if zeroshot_paragraphs:
        _compare("", dialogue_indices, paragraphs,
                 "speaker_llm_zeroshot", "LLM-zeroshot",
                 "speaker_llm_context", "LLM-context")

    # ── Сохраняем ────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tmp = output_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=True, indent=2))
    os.replace(tmp, output_path)

    print(f"\nSaved: {output_path}")


def _load_characters_from_file(characters_path: str) -> list[str]:
    """Load character names (+ aliases) from characters.json produced by character_extractor."""
    if not os.path.exists(characters_path):
        return []
    with open(characters_path, encoding="utf-8") as f:
        raw = json.load(f)
    chars_data = raw if isinstance(raw, list) else raw.get("characters", [])
    names: list[str] = []
    for c in chars_data:
        name = c.get("name") or c.get("character")
        if name:
            names.append(name)
        for alias in c.get("aliases", []):
            if alias and alias not in names:
                names.append(alias)
    return names


def run_by_scenes(
    input_path: str,
    output_path: str,
    max_scene_size: int = 20,
    characters_path: str | None = None,
) -> None:
    """
    Attribute dialogue chapter by chapter, scene by scene.
    Processes parsed_with_scenes.json — each scene is one LLM call.
    If a scene exceeds max_scene_size paragraphs it is split into chunks.
    If characters_path is given, loads character list from characters.json
    (run character_extractor before this step for best results).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    client = anthropic.Anthropic(api_key=api_key)

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    # Prefer explicit characters.json; fall back to names found in speaker fields
    if characters_path:
        characters = _load_characters_from_file(characters_path)
    else:
        characters = extract_characters(data)
    print(f"Known characters: {len(characters)}  —  {', '.join(characters) or 'none yet'}")
    system_prompt = _build_system_prompt(characters)

    total_attributed = 0

    for chapter in data["chapters"]:
        print(f"\n[{chapter['id']}] {chapter['title']}")

        for scene_label, paragraphs in _iter_scenes(chapter):
            if not paragraphs:
                continue

            dialogue_count = sum(1 for p in paragraphs if p.get("type") == "dialogue")
            if dialogue_count == 0:
                continue

            print(f"  Scene '{scene_label}'  ({len(paragraphs)} paragraphs, {dialogue_count} dialogues)")

            # Split large scenes into chunks to stay within token limits
            chunk_size = max_scene_size
            for chunk_start in range(0, len(paragraphs), chunk_size):
                chunk = paragraphs[chunk_start: chunk_start + chunk_size]
                attributions = attribute_chunk(client, chunk, offset=chunk_start, system_prompt=system_prompt)

                for idx, speaker in attributions.items():
                    if idx < len(paragraphs):
                        paragraphs[idx]["speaker_llm_context"] = speaker
                        if speaker:
                            total_attributed += 1

            time.sleep(0.3)

    # Save
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    tmp = output_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, output_path)
    print(f"\nSaved: {output_path}  (total attributed: {total_attributed})")


def run_on_db(book_id: int, db, chapter_id: int | None = None,
              max_scene_size: int = CHUNK_SIZE) -> None:
    """
    Run dialogue attribution directly on DB paragraphs.
    Reads Scene → Paragraph from DB, updates Paragraph.speaker.
    """
    from backend.models import (
        Chapter as DBChapter,
        Paragraph as DBParagraph,
        Scene as DBScene,
        Character as DBCharacter,
        CharacterAlias,
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    client = anthropic.Anthropic(api_key=api_key)

    # Load known characters from DB
    chars = db.query(DBCharacter).filter(DBCharacter.book_id == book_id).all()
    characters = []
    for c in chars:
        characters.append(c.name)
        for alias in c.aliases:
            if alias.alias not in characters:
                characters.append(alias.alias)

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
            # Process scene by scene
            for scene in scenes:
                db_paras = (db.query(DBParagraph)
                              .filter(DBParagraph.scene_id == scene.id)
                              .order_by(DBParagraph.index)
                              .all())

                dialogue_count = sum(1 for p in db_paras if p.type == "dialogue")
                if dialogue_count == 0:
                    continue

                print(f"  Scene {scene.scene_index}  ({len(db_paras)} paras, {dialogue_count} dialogues)")

                para_dicts = [{"text": p.text, "type": p.type} for p in db_paras]

                for chunk_start in range(0, len(db_paras), max_scene_size):
                    chunk      = para_dicts[chunk_start: chunk_start + max_scene_size]
                    db_chunk   = db_paras[chunk_start: chunk_start + max_scene_size]
                    attributions = attribute_chunk(client, chunk, offset=chunk_start,
                                                   system_prompt=system_prompt)
                    for idx, speaker in attributions.items():
                        if idx < len(db_chunk) and speaker:
                            db_chunk[idx].speaker = speaker
                            total_attributed += 1

                time.sleep(0.3)
        else:
            # No scenes — process whole chapter as one chunk
            db_paras = (db.query(DBParagraph)
                          .filter(DBParagraph.chapter_id == ch.id)
                          .order_by(DBParagraph.index)
                          .all())

            para_dicts = [{"text": p.text, "type": p.type} for p in db_paras]

            for chunk_start in range(0, len(db_paras), max_scene_size):
                chunk    = para_dicts[chunk_start: chunk_start + max_scene_size]
                db_chunk = db_paras[chunk_start: chunk_start + max_scene_size]
                attributions = attribute_chunk(client, chunk, offset=chunk_start,
                                               system_prompt=system_prompt)
                for idx, speaker in attributions.items():
                    if idx < len(db_chunk) and speaker:
                        db_chunk[idx].speaker = speaker
                        total_attributed += 1

    db.commit()
    print(f"\nAttribution done. Total attributed: {total_attributed}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("book", help="Name of book example: alice, pride_prejudice")
    parser.add_argument("--chapter", type=int, default=None, help="Index of chapter ")
    parser.add_argument("--all-chapters", action="store_true", help="Process all chapters")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--input",    default=None, help="Input JSON (default: parsed_final.json)")
    parser.add_argument("--zeroshot", default=None, help="JSON to compare")
    parser.add_argument("--output",   default=None, help="Output JSON (default: parsed_llm_context.json)")
    args = parser.parse_args()

    if not args.all_chapters and args.chapter is None:
        parser.error("Enter --chapter N or --all-chapters")

    base = f"storage/uploads/{args.book}"
    input_path    = args.input    or f"{base}/parsed_final.json"
    zeroshot_path = args.zeroshot or f"{base}/parsed_llm_zeroshot.json"
    output_path   = args.output   or f"{base}/parsed_llm_context.json"

    if args.all_chapters:
        with open(input_path, encoding="utf-8") as f:
            total_chapters = len(json.load(f)["chapters"])
        for idx in range(total_chapters):
            print(f"\n{'='*50}")
            print(f"ГЛАВА {idx}/{total_chapters - 1}")
            print(f"{'='*50}")
            src = output_path if idx > 0 and os.path.exists(output_path) else input_path
            run_with_context(src, zeroshot_path, output_path, chapter_idx=idx, chunk_size=args.chunk_size)
    else:
        run_with_context(input_path, zeroshot_path, output_path, chapter_idx=args.chapter, chunk_size=args.chunk_size)