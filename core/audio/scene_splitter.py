"""
Scene splitter: divides each chapter into scenes using LLM.
Creates Scene records in DB and assigns scene_id to every paragraph.
"""

import json
import os
import re

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


def _build_prompt(paragraphs: list[dict]) -> str:
    """Format chapter paragraphs as a numbered list for the LLM.

    Each paragraph is truncated to 150 characters to reduce token usage
    while preserving enough context for location-based scene detection.
    """
    lines = [
        f"[{i}] ({p.get('type', 'narration')}) {p['text'][:150]}"
        for i, p in enumerate(paragraphs)
    ]
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


def _call_llm(client: anthropic.Anthropic, paragraphs: list[dict]) -> list[dict]:
    """Send chapter paragraphs to the LLM and return scene boundaries.

    Re-indexes scene_id sequentially in case the LLM returns non-contiguous ids.
    Raises ValueError if the response does not contain a valid JSON array.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_prompt(paragraphs)}],
    )
    raw = response.content[0].text

    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array in response:\n{raw}")

    scenes = json.loads(match.group())

    # Re-assign scene_id by order in case LLM returned non-contiguous ids
    for i, s in enumerate(scenes):
        s["scene_id"] = i

    return scenes


def _process_chapter(client: anthropic.Anthropic, ch, db) -> None:
    """Detect scenes for a single chapter and persist Scene + Paragraph.scene_id to DB."""
    from backend.models import Paragraph as DBParagraph, Scene as DBScene

    db_paras = (db.query(DBParagraph)
                  .filter(DBParagraph.chapter_id == ch.id)
                  .order_by(DBParagraph.index)
                  .all())

    if not db_paras:
        print(f"  [{ch.chapter_id}] {ch.title[:50]} — no paragraphs, skipping")
        return

    print(f"  [{ch.chapter_id}] {ch.title[:50]}  ({len(db_paras)} paragraphs)")

    para_dicts = [{"text": p.text, "type": p.type} for p in db_paras]
    scenes = _call_llm(client, para_dicts)
    print(f"    Scenes: {len(scenes)}")

    # Replace old scenes for this chapter
    db.query(DBScene).filter(DBScene.chapter_id == ch.id).delete()
    db.flush()

    for scene in scenes:
        start          = scene["start_paragraph"]
        end            = min(scene["end_paragraph"], len(db_paras) - 1)
        paras_in_scene = db_paras[start:end + 1]
        preview        = " ".join(p.text for p in paras_in_scene[:3])[:300]

        db_scene = DBScene(
            chapter_id=ch.id,
            scene_index=scene["scene_id"],
            preview=preview,
            location=scene.get("location"),
        )
        db.add(db_scene)
        db.flush()

        for p in paras_in_scene:
            p.scene_id = db_scene.id

    # Assign any leftover paragraphs (past last scene boundary) to the last scene
    if scenes:
        last_end = scenes[-1]["end_paragraph"]
        if last_end < len(db_paras) - 1:
            last_scene = (db.query(DBScene)
                            .filter(DBScene.chapter_id == ch.id)
                            .order_by(DBScene.scene_index.desc())
                            .first())
            if last_scene:
                for p in db_paras[last_end + 1:]:
                    p.scene_id = last_scene.id

    db.flush()
    print(f"    Done.")


def run_on_db(book_id: int, db, chapter_id: int | None = None) -> None:
    """Run scene detection for all chapters in the book, creating Scene records."""
    from backend.models import Chapter as DBChapter

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    client = anthropic.Anthropic(api_key=api_key)

    chapters_q = db.query(DBChapter).filter(DBChapter.book_id == book_id)
    if chapter_id is not None:
        chapters_q = chapters_q.filter(DBChapter.chapter_id == chapter_id)
    chapters = chapters_q.order_by(DBChapter.chapter_index).all()

    for ch in chapters:
        _process_chapter(client, ch, db)

    db.commit()
    print("Scene detection done.")