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
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"

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
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(characters, voices)}],
    )
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

    # Pick narrator voice deterministically — prefer narrative_story use_case
    narrator_voice = next(
        (v for v in voices if v.get("use_case") == "narrative_story"),
        None,
    ) or next(
        (v for v in voices if "narrat" in v["name"].lower()),
        voices[0],
    )
    print(f"Narrator:   {narrator_voice['name']} ({narrator_voice['id']})")
    print("Asking LLM to assign voices for characters...\n")

    voice_map = call_llm(client, characters, voices)
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
