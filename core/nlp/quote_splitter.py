"""
Quote splitter: splits paragraphs that mix narration and dialogue into separate parts.

A paragraph like:
  She smiled. "Come in," said Alice. "It's open."
becomes three paragraphs: narration / dialogue / dialogue.
"""

import re

# Matches fully closed quotes: “text” or “text” (curly quotes)
QUOTE_RE = re.compile(r'[“”](.*?)[“”]', re.DOTALL)

# Matches an opening quote with no closing quote (runs to end of string)
UNCLOSED_QUOTE_RE = re.compile(r'[“””](.*?)$', re.DOTALL)


def find_speaker(context: str, known_speakers: set[str]) -> str | None:
    # Returns the first known speaker name found in context, or None.
    if not context.strip():
        return None

    context_lower = context.lower()
    for name in known_speakers:
        if name.lower() in context_lower:
            return name

    return None


def split_paragraph(para: dict, known_speakers: set[str]) -> list[dict]:
    """Split a mixed paragraph into separate narration and dialogue parts.

    Looks for quoted strings and extracts them as dialogue paragraphs.
    The surrounding text becomes narration. Speaker is inferred from
    the text immediately before or after each quote.

    Returns the original paragraph unchanged if no meaningful split is possible.
    """
    text = para["text"]
    matches = list(QUOTE_RE.finditer(text))

    if not matches:
        # No closed quotes — check for an unclosed quote running to end of string
        m = UNCLOSED_QUOTE_RE.search(text)
        if not m:
            return [para]
        before = text[:m.start()].strip().strip('",;: ')
        quote  = m.group(1).strip()
        if not quote:
            return [para]
        parts = []
        if len(before) > 3:
            parts.append(_make_para(para, before, "narration", None))
        speaker = find_speaker(before, known_speakers)
        if not speaker and para["type"] == "dialogue":
            speaker = para.get("speaker")
        parts.append(_make_para(para, quote, "dialogue", speaker))
        return parts

    parts = []
    cursor = 0

    for m in matches:
        before     = text[cursor:m.start()].strip().strip('",;: ')
        quote      = m.group(1).strip()
        cursor     = m.end()
        after_peek = text[cursor:cursor + 100]  # brief look-ahead for attribution

        if len(before) > 3:
            parts.append(_make_para(para, before, "narration", None))

        if len(quote) > 1:
            speaker = (
                find_speaker(before, known_speakers) or
                find_speaker(after_peek, known_speakers)
            )
            if not speaker and para["type"] == "dialogue":
                speaker = para.get("speaker")
            parts.append(_make_para(para, quote, "dialogue", speaker))

    after = text[cursor:].strip().strip('",;: ')
    if len(after) > 3:
        parts.append(_make_para(para, after, "narration", None))

    if not parts:
        return [para]

    if len(parts) == 1 and parts[0]["type"] == para["type"]:
        return [para]

    return parts


def _make_para(source: dict, text: str, ptype: str, speaker: str | None) -> dict:
    return {
        "text":       text,
        "type":       ptype,
        "chapter_id": source["chapter_id"],
        "speaker":    speaker if ptype == "dialogue" else None,
    }


def _needs_splitting(para: dict) -> bool:
    """Return True if the paragraph contains quotes that should be extracted.

    Narration paragraphs with any quotes always need splitting.
    Dialogue paragraphs need splitting only when the quoted portion is less
    than 85% of the text (meaning there is significant surrounding narration).
    """
    text = para["text"]

    closed_matches = list(QUOTE_RE.finditer(text))
    unclosed_match = UNCLOSED_QUOTE_RE.search(text) if not closed_matches else None

    if not closed_matches and not unclosed_match:
        return False

    if para["type"] == "narration":
        return True

    if para["type"] == "dialogue" and closed_matches:
        quoted_len = sum(len(m.group(1)) for m in closed_matches)
        return quoted_len < len(text) * 0.85

    return False


def collect_speakers_from_db(book_id: int, db) -> set[str]:
    """Collect known speaker names from DB paragraphs."""
    from backend.models import Paragraph as DBParagraph, Chapter as DBChapter
    rows = (db.query(DBParagraph.speaker)
              .join(DBChapter)
              .filter(DBChapter.book_id == book_id,
                      DBParagraph.speaker.isnot(None))
              .all())
    speakers = set()
    for (s,) in rows:
        s = s.strip()
        if 2 <= len(s) <= 30 and re.match(r"^[A-Za-z][A-Za-z '\-]+$", s):
            speakers.add(s)
    return speakers


def run_on_db(book_id: int, db, chapter_id: int | None = None) -> None:
    """Split mixed paragraphs into narration + dialogue parts and re-index.

    Deletes all paragraphs for each chapter and re-inserts them with updated
    indexes. scene_id is reset to None since scene detection must be re-run
    after splitting changes the paragraph structure.
    """
    from backend.models import Paragraph as DBParagraph, Chapter as DBChapter

    known_speakers = collect_speakers_from_db(book_id, db)
    print(f"Known speakers: {len(known_speakers)}")

    chapters_q = db.query(DBChapter).filter(DBChapter.book_id == book_id)
    if chapter_id is not None:
        chapters_q = chapters_q.filter(DBChapter.chapter_id == chapter_id)
    chapters = chapters_q.order_by(DBChapter.chapter_index).all()

    for ch in chapters:
        db_paras = (db.query(DBParagraph)
                      .filter(DBParagraph.chapter_id == ch.id)
                      .order_by(DBParagraph.index)
                      .all())

        new_paras = []
        splits = 0

        for para in db_paras:
            para_dict = {
                "text":       para.text,
                "type":       "narration" if para.type in ("text", "narration") else para.type,
                "chapter_id": para.chapter_id,
                "speaker":    para.speaker,
            }

            if _needs_splitting(para_dict):
                result = split_paragraph(para_dict, known_speakers)
                if len(result) > 1:
                    splits += 1
                new_paras.extend(result)
            else:
                new_paras.append(para_dict)

        # Replace all paragraphs for this chapter with re-indexed versions
        db.query(DBParagraph).filter(DBParagraph.chapter_id == ch.id).delete()
        db.flush()

        for i, p in enumerate(new_paras):
            db.add(DBParagraph(
                chapter_id=ch.id,
                scene_id=None,  # scenes are re-detected in next pipeline step
                index=i,
                text=p["text"],
                type=p["type"],
                speaker=p.get("speaker") if p["type"] == "dialogue" else None,
            ))

        print(f"  [{ch.chapter_id}] {ch.title[:50]:<50} {len(db_paras)} → {len(new_paras)}  (+{splits} splits)")

    db.commit()
    print("Quote splitting done.")