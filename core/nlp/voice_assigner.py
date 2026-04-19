"""
Voice assigner: matches book characters to TTS voices using LLM.

Reads characters.json + fetches voices from ElevenLabs/Azure,
then uses LLM (Haiku) to assign the best voice to each character.

Usage:
    python -m core.nlp.voice_assigner alice
    python -m core.nlp.voice_assigner alice --preview
"""

import json
import os
import re
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"

STYLE_SYSTEM_PROMPT = """\
You are an audio director for an audiobook production.
Given a character's description, assign ElevenLabs voice style parameters.

Parameters:
- stability (0.0-1.0): LOW = emotional/unpredictable, HIGH = calm/consistent
- style (0.0-1.0): LOW = neutral delivery, HIGH = expressive/dramatic
- similarity_boost (0.0-1.0): how closely to match the original voice character (usually 0.65-0.85)
- speaker_boost (true/false): enhances voice clarity (true for most characters)

Guidelines:
- aggressive/dramatic/passionate → stability: 0.15-0.30, style: 0.75-0.95
- nervous/timid/anxious → stability: 0.55-0.70, style: 0.20-0.40
- calm/wise/philosophical → stability: 0.80-0.95, style: 0.05-0.20
- curious/energetic/playful → stability: 0.35-0.55, style: 0.50-0.70
- cold/contemptuous/aloof → stability: 0.80-0.90, style: 0.10-0.25
- cheerful/friendly/warm → stability: 0.45-0.60, style: 0.55-0.75

Return ONLY valid JSON object, no explanation:
{
  "Alice": {"stability": 0.4, "style": 0.6, "similarity_boost": 0.75, "speaker_boost": true},
  "the Queen": {"stability": 0.2, "style": 0.9, "similarity_boost": 0.75, "speaker_boost": true}
}
"""

SYSTEM_PROMPT = """\
You are a casting director for an audiobook production.
You will receive a list of book characters with their descriptions,
and a list of available TTS voices with their characteristics.

Assign the best matching voice to each character.

Rules:
- Match gender first (male → male voice, female → female voice)
- Then match age (child, young_adult, middle_aged, old)
- Then match personality and accent when possible
- Each voice can be assigned to multiple characters if needed
- Do NOT include NARRATOR — it will be assigned separately
- Return ONLY valid JSON object, no explanation

Output format:
{
  "NARRATOR": "voice_id_here",
  "Alice": "voice_id_here",
  "the White Rabbit": "voice_id_here",
  ...
}
"""


def get_elevenlabs_voices() -> list[dict]:
    from elevenlabs import ElevenLabs
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY not set in .env")
    client = ElevenLabs(api_key=api_key)
    voices = client.voices.get_all().voices
    return [
        {
            "id":          v.voice_id,
            "name":        v.name,
            "gender":      (v.labels or {}).get("gender", "unknown"),
            "age":         (v.labels or {}).get("age", "unknown"),
            "accent":      (v.labels or {}).get("accent", "unknown"),
            "use_case":    (v.labels or {}).get("use_case", ""),
            "descriptive": (v.labels or {}).get("descriptive", ""),
            "description": v.description or "",
        }
        for v in voices
    ]



def build_prompt(characters: list[dict], voices: list[dict]) -> str:
    chars_text = "CHARACTERS:\n"
    for c in characters:
        chars_text += (
            f"- {c['name']}: {c['gender']}, {c['age']}, "
            f"personality: {c['personality']}, accent: {c['accent']}\n"
            f"  voice_description: {c.get('voice_description', '')}\n"
        )

    voices_text = "\nAVAILABLE VOICES:\n"
    for v in voices:
        desc = v['description'] or v['descriptive']
        voices_text += (
            f"- {v['id']}: {v['gender']}, {v['age']}, accent: {v['accent']}"
            + (f", {desc}" if desc else "") + "\n"
        )

    return chars_text + voices_text + "\nAssign voices. Include NARRATOR."


def call_llm(client: anthropic.Anthropic, characters: list[dict], voices: list[dict]) -> dict:
    for attempt in range(5):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_prompt(characters, voices)}],
            )
            break
        except (anthropic.RateLimitError, anthropic.OverloadedError) as e:
            wait = 15 * (2 ** attempt)
            print(f"{type(e).__name__}, retrying in {wait}s (attempt {attempt + 1}/5)...")
            time.sleep(wait)
    else:
        raise RuntimeError("API overloaded after 5 retries")

    raw = response.content[0].text

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object in response:\n{raw}")

    try:
        return json.loads(match.group())
    except json.JSONDecodeError as e:
        print(f"\nRaw response:\n{raw}\n")
        raise ValueError(f"Invalid JSON: {e}") from e


def run(
    book: str,
    characters_file: str = "characters.json",
    output_file: str | None = None,
    preview: bool = False,
) -> None:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    base = Path(f"storage/uploads/{book}")
    chars_path = base / characters_file

    if not chars_path.exists():
        raise FileNotFoundError(f"characters.json not found. Run character_extractor first.")

    with open(chars_path, encoding="utf-8") as f:
        characters = json.load(f)

    print(f"Characters: {len(characters)}")
    print(f"Fetching voices from ElevenLabs...", end=" ", flush=True)

    voices = get_elevenlabs_voices()

    print(f"{len(voices)} voices found")

    RIVER_VOICE_ID = "SAz9YHcvj6GT2YYXdXww"
    narrator_voice = next(
        (v for v in voices if v["id"] == RIVER_VOICE_ID), None
    ) or next(
        (v for v in voices if v.get("use_case") == "narrative_story"), voices[0]
    )
    print(f"Narrator:   {narrator_voice['name']} ({narrator_voice['id']})")
    print("Asking LLM to assign voices for characters...\n")

    # Exclude narrator voice so LLM can't assign it to any character
    character_voices = [v for v in voices if v["id"] != narrator_voice["id"]]
    voice_map = call_llm(client, characters, character_voices)
    voice_map["NARRATOR"] = narrator_voice["id"]

    id_to_name = {v["id"]: v["name"] for v in voices}

    print(f"  {'Character':<25} {'Voice name':<40} {'Voice ID'}")
    print("  " + "-" * 90)
    for character, voice_id in voice_map.items():
        voice_name = id_to_name.get(voice_id, "???")
        print(f"  {character:<25} {voice_name:<40} {voice_id}")

    if preview:
        print("\nPreview done. Run without --preview to save.")
        return

    out_name = output_file or "voice_map_elevenlabs.json"
    out_path = base / out_name
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(voice_map, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


def _call_style_batch(client: anthropic.Anthropic, characters: list[dict]) -> dict:
    """Call LLM for a single batch of characters, return style dict."""
    chars_text = "CHARACTERS:\n"
    for c in characters:
        chars_text += (
            f"- {c['name']}: personality={c['personality']}, "
            f"voice_description={c.get('voice_description', '')}\n"
        )

    for attempt in range(5):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=STYLE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": chars_text}],
            )
            break
        except (anthropic.RateLimitError, anthropic.OverloadedError) as e:
            wait = 15 * (2 ** attempt)
            print(f"{type(e).__name__}, retrying in {wait}s...")
            time.sleep(wait)
    else:
        raise RuntimeError("API overloaded after 5 retries")

    raw = response.content[0].text
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON in style response:\n{raw}")
    return json.loads(match.group())


def call_llm_style(client: anthropic.Anthropic, characters: list[dict], batch_size: int = 8) -> dict:
    """Ask LLM to assign voice style parameters, processing in batches."""
    result = {}
    for i in range(0, len(characters), batch_size):
        batch = characters[i:i + batch_size]
        print(f"  Styling batch {i // batch_size + 1}/{(len(characters) + batch_size - 1) // batch_size} ({len(batch)} characters)...")
        try:
            batch_result = _call_style_batch(client, batch)
            result.update(batch_result)
        except Exception as e:
            print(f"  Warning: batch failed: {e}")
    return result


def run_on_db(book_id: int, db, engine: str = "elevenlabs") -> None:
    """
    Assign TTS voices to characters reading from DB and writing back to DB.
    Updates Character.voice_id and Character.engine fields.
    """
    from backend.models import Character as DBCharacter

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    db_chars = db.query(DBCharacter).filter(DBCharacter.book_id == book_id).all()
    if not db_chars:
        raise ValueError("No characters in DB — run character extraction first (step 4)")

    # Convert DB characters to dicts for existing LLM logic
    characters = [
        {
            "name":              c.name,
            "gender":            c.gender or "unknown",
            "age":               c.age or "unknown",
            "personality":       c.personality or "",
            "accent":            c.accent or "unknown",
            "voice_description": c.voice_desc or "",
        }
        for c in db_chars
    ]

    print(f"Characters: {len(characters)}")
    print("Fetching voices from ElevenLabs...", end=" ", flush=True)

    voices = get_elevenlabs_voices()
    print(f"{len(voices)} voices found")

    RIVER_VOICE_ID = "SAz9YHcvj6GT2YYXdXww"
    narrator_voice = next(
        (v for v in voices if v["id"] == RIVER_VOICE_ID), None
    ) or next(
        (v for v in voices if v.get("use_case") == "narrative_story"), voices[0]
    )
    print(f"Narrator: {narrator_voice['name']} ({narrator_voice['id']})")

    character_voices = [v for v in voices if v["id"] != narrator_voice["id"]]
    voice_map = call_llm(client, characters, character_voices)
    voice_map["NARRATOR"] = narrator_voice["id"]

    # Save voice assignments to DB
    name_to_char = {c.name: c for c in db_chars}
    # Also index by aliases
    for c in db_chars:
        for alias in c.aliases:
            name_to_char[alias.alias] = c

    def find_char(name: str):
        """Find character by exact name, then by partial match."""
        if name in name_to_char:
            return name_to_char[name]
        name_lower = name.lower()
        # Try: DB name contains LLM name or vice versa
        for db_name, ch in name_to_char.items():
            if name_lower in db_name.lower() or db_name.lower() in name_lower:
                return ch
        return None

    assigned = 0
    for char_name, voice_id in voice_map.items():
        if char_name == "NARRATOR":
            continue
        db_char = find_char(char_name)
        if db_char:
            db_char.voice_id = voice_id
            db_char.engine   = engine
            assigned += 1

    db.commit()
    print(f"Assigned voices to {assigned}/{len(db_chars)} characters in DB.")

    # Assign voice style parameters per character personality
    print("Assigning voice style parameters...")
    try:
        style_map = call_llm_style(client, characters)
        styled = 0
        for char_name, params in style_map.items():
            db_char = find_char(char_name)
            if db_char:
                db_char.voice_stability        = params.get("stability")
                db_char.voice_style            = params.get("style")
                db_char.voice_similarity_boost = params.get("similarity_boost")
                db_char.voice_speaker_boost    = params.get("speaker_boost")
                styled += 1
        db.commit()
        print(f"Styled {styled}/{len(db_chars)} characters in DB.")
    except Exception as e:
        print(f"Warning: voice style assignment failed: {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("book",      help="Book name, e.g.: alice")
    parser.add_argument("--output",  default=None)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()

    run(
        book=args.book,
        output_file=args.output,
        preview=args.preview,
    )
