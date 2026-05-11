"""
Character extractor: LLM-based extraction per scene → deduplication → parallel profiling.
Saves Character + CharacterAlias records directly to DB.

Pipeline:
  1. _extract_speakers_from_scene — per scene, parallel (max 3 workers)
  2. _deduplicate               — single call, merges aliases
  3. _profile_character         — per canonical character, parallel (max 3 workers)
"""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"

# Instructs the LLM to return only names of characters who have dialogue in the excerpt.
EXTRACT_SYSTEM_PROMPT = """\
You are a literary analyst. Read the text excerpt and list every character who SPEAKS in it.

Rules:
- Only include characters who actually say something (have dialogue)
- Use the exact name or title as it appears in the text (e.g. "White Rabbit", "Cheshire Cat")
- Do NOT include the narrator
- Do NOT include unnamed characters ("a man", "someone")

Return ONLY a JSON array of names, no explanation:
["Alice", "White Rabbit"]
"""

# Instructs the LLM to merge variant names  into canonical entries.
DEDUP_SYSTEM_PROMPT = """\
You are a literary analyst. You will receive a list of character names extracted from different parts of a book.

Your task:
1. Identify names that refer to the same character (e.g. "Cat" and "Cheshire Cat" are the same)
2. Choose the canonical name (most recognizable/common form)
3. List aliases for each

Return ONLY a valid JSON array, no explanation:
[
  {"name": "Cheshire Cat", "aliases": ["Cat"]},
  {"name": "Alice", "aliases": []}
]
"""

# Instructs the LLM to build a voice profile for a character based on scene excerpts.
# Returns null for crowds, locations, or the narrator — these are not voiced as characters.
PROFILE_SYSTEM_PROMPT = """\
You are a literary analyst for audiobook production.
You will receive a character name and text excerpts where this character appears.

Return a profile JSON if this character has any dialogue or active role in the story.
Characters can be human, animal, magical creature, or any entity — all are valid if they speak or act.
Return null ONLY if the name refers to an unnamed crowd ("people", "crowd"), a location, or the narrator.

Return ONLY valid JSON object or null:
{
  "name": "Alice",
  "gender": "female",
  "age": "child",
  "personality": "curious, brave, imaginative, polite",
  "accent": "british",
  "voice_description": "A young girl's voice, bright and curious, slightly formal for her age."
}
"""


def _extract_speakers_from_scene(client: anthropic.Anthropic, scene_text: str) -> list[str]:
    """Ask Haiku to find all speaking characters in a scene.

    Input is truncated to 3000 characters to stay within token limits.
    Returns an empty list on any error to keep the parallel pipeline fault-tolerant.
    """
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=256,
            temperature=0,
            system=EXTRACT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": scene_text[:3000]}],
        )
        raw = response.content[0].text.strip()
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        return json.loads(match.group())
    except Exception:
        return []


def _deduplicate(client: anthropic.Anthropic, all_names: list[str]) -> list[dict]:
    """Ask Haiku to merge duplicate names and return canonical list with aliases.

    Deduplication is done in a single LLM call with all raw names at once.
    Falls back to returning each name as-is (no aliases) if the LLM call fails.
    """
    unique = sorted(set(all_names))
    if not unique:
        return []

    prompt = f"Character names found across the book:\n{json.dumps(unique)}"
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            temperature=0,
            system=DEDUP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return [{"name": n, "aliases": []} for n in unique]
        return json.loads(match.group())
    except Exception:
        return [{"name": n, "aliases": []} for n in unique]


def _profile_character(client: anthropic.Anthropic, name: str, scene_texts: list[str], aliases: list[str] | None = None) -> dict | None:
    """Ask Haiku to profile a single character using scenes where they appear.

    Uses up to 5 scene excerpts (300 chars each) to keep the prompt concise.
    If the character is a first-person narrator (alias "I"), a note is added
    so the LLM can correctly identify them from excerpts that use "I said...".
    Retries up to 3 times on JSON errors; backs off on rate limit errors.
    Returns None if the LLM decides the name is not a valid character.
    """
    excerpts = "\n---\n".join(t[:300] for t in scene_texts[:5])
    note = ""
    if aliases and "I" in aliases:
        note = f'\nNote: This character is the first-person narrator — they speak as "I" throughout the text.\n'
    prompt = f"Character: {name}{note}\n\nText excerpts:\n{excerpts}"
    for attempt in range(3):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=512,
                temperature=0,
                system=PROFILE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            if re.fullmatch(r"null[.,]?", raw.strip().lower()):
                return None
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return None
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            if attempt == 2:
                return None
            time.sleep(1)
        except (anthropic.RateLimitError, anthropic.InternalServerError):
            time.sleep(15 * (attempt + 1))
    return None


def _build_scene_texts(book_id: int, db) -> dict[int, str]:
    """Return {scene_id: text} for every scene in the book.

    Falls back to treating the whole chapter as one scene if scene detection
    has not been run yet (no Scene records exist for that chapter).
    """
    from backend.models import (
        Chapter as DBChapter,
        Paragraph as DBParagraph,
        Scene as DBScene,
    )
    scene_texts: dict[int, str] = {}
    chapters = (db.query(DBChapter)
                  .filter(DBChapter.book_id == book_id)
                  .order_by(DBChapter.chapter_index)
                  .all())
    for ch in chapters:
        scenes = (db.query(DBScene)
                    .filter(DBScene.chapter_id == ch.id)
                    .order_by(DBScene.scene_index)
                    .all())
        if scenes:
            for scene in scenes:
                paras = (db.query(DBParagraph)
                           .filter(DBParagraph.scene_id == scene.id)
                           .order_by(DBParagraph.index)
                           .all())
                scene_texts[scene.id] = " ".join(p.text for p in paras)
        else:
            paras = (db.query(DBParagraph)
                       .filter(DBParagraph.chapter_id == ch.id)
                       .order_by(DBParagraph.index)
                       .all())
            scene_texts[ch.id] = " ".join(p.text for p in paras)
    return scene_texts


def _save_characters_to_db(book_id: int, profiles: list[dict], db) -> None:
    """Delete existing characters for the book and insert new ones with aliases.

    Re-running always produces a clean result — no stale records are left behind.
    """
    from backend.models import (
        Character as DBCharacter,
        CharacterAlias,
    )
    char_ids = [c.id for c in db.query(DBCharacter.id).filter(DBCharacter.book_id == book_id).all()]
    if char_ids:
        db.query(CharacterAlias).filter(CharacterAlias.character_id.in_(char_ids)).delete(synchronize_session=False)
    db.query(DBCharacter).filter(DBCharacter.book_id == book_id).delete()
    db.flush()

    for c in profiles:
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

        for alias in c.get("aliases", []):
            alias = alias.strip()
            if alias and alias != name:
                db.add(CharacterAlias(character_id=db_char.id, alias=alias))

    db.commit()
    print(f"Saved {len(profiles)} characters to DB.")


def run_on_db(book_id: int, db) -> None:
    """Extract characters via LLM per scene → deduplicate → profile in parallel.

    Orchestrates three LLM steps and persists results to DB.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    client = anthropic.Anthropic(api_key=api_key)

    # Build input: scene texts from DB
    scene_texts = _build_scene_texts(book_id, db)
    print(f"Extracting speakers from {len(scene_texts)} scenes in parallel...")

    # Step 1: extract speakers per scene in parallel
    scene_speakers: dict[int, list[str]] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_extract_speakers_from_scene, client, text): scene_id
            for scene_id, text in scene_texts.items()
        }
        for future in as_completed(futures):
            scene_id = futures[future]
            scene_speakers[scene_id] = future.result()

    all_names = [name for speakers in scene_speakers.values() for name in speakers]
    print(f"Found {len(set(all_names))} raw names: {', '.join(sorted(set(all_names)))}")

    # Step 2: deduplicate raw names into canonical characters with aliases
    print("Deduplicating...")
    canonical_list = _deduplicate(client, all_names)
    print(f"After dedup: {[c['name'] for c in canonical_list]}")

    # Build reverse map: alias → canonical name
    name_to_canonical: dict[str, str] = {}
    for entry in canonical_list:
        name_to_canonical[entry["name"]] = entry["name"]
        for alias in entry.get("aliases", []):
            name_to_canonical[alias] = entry["name"]

    # Collect scene texts per canonical character for profiling
    char_scenes: dict[str, list[str]] = {entry["name"]: [] for entry in canonical_list}
    for scene_id, speakers in scene_speakers.items():
        for raw_name in speakers:
            canonical = name_to_canonical.get(raw_name)
            if canonical and scene_texts.get(scene_id):
                char_scenes[canonical].append(scene_texts[scene_id])

    # Step 3: profile each character in parallel
    print(f"Profiling {len(canonical_list)} characters in parallel...")
    profiles: list[dict] = []
    aliases_map: dict[str, list[str]] = {e["name"]: e.get("aliases", []) for e in canonical_list}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(
                _profile_character, client, entry["name"],
                char_scenes[entry["name"]], aliases_map.get(entry["name"], [])
            ): entry["name"]
            for entry in canonical_list
        }
        for future in as_completed(futures):
            name = futures[future]
            profile = future.result()
            if profile:
                profile["aliases"] = aliases_map.get(name, [])
                profiles.append(profile)
                print(f"  ✓ {profile['name']}")
            else:
                print(f"  ✗ {name} (skipped)")

    # Deduplicate profiles by name (case-insensitive) — keep first occurrence
    seen_names: set[str] = set()
    unique_profiles: list[dict] = []
    for p in profiles:
        key = p["name"].lower()
        if key not in seen_names:
            seen_names.add(key)
            unique_profiles.append(p)

    print(f"Final: {len(unique_profiles)} characters")
    _save_characters_to_db(book_id, unique_profiles, db)