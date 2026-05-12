"""
Quote splitter: splits paragraphs that mix narration and dialogue into separate parts.

A paragraph like:
  She smiled. "Come in," said Alice. "It's open."
becomes three paragraphs: narration / dialogue / dialogue.
"""

import re

# Matches fully closed double quotes (curly or straight) OR single quotes at word boundaries.
# Single-quote pattern uses word-boundary guards to skip apostrophes in words like "Alice's".
QUOTE_RE = re.compile(
    r'[“”"](.*?)[“”"]|(?<!\w)\'(.*?)\'(?!\w)',
    re.DOTALL,
)

# Matches an opening quote with no closing quote running to end of string
UNCLOSED_QUOTE_RE = re.compile(r'[“”"\'](.*?)$', re.DOTALL)


def _quote_text(m: re.Match) -> str:
    # group 1 = double-quote match, group 2 = single-quote match
    g1 = m.group(1)
    g2 = m.group(2)
    return (g1 if g1 is not None else (g2 if g2 is not None else "")).strip()


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
    """Split a mixed paragraph into separate narration and dialogue parts."""
    text = para["text"]
    matches = list(QUOTE_RE.finditer(text))

    if not matches:
        m = UNCLOSED_QUOTE_RE.search(text)
        if not m:
            return [para]
        before = text[:m.start()].strip().strip('",;: ')
        g1 = m.group(1)
        quote = (g1 if g1 is not None else "").strip()
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
        quote      = _quote_text(m)
        cursor     = m.end()
        after_peek = text[cursor:cursor + 100]

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
    """Return True if the paragraph contains quotes that should be extracted."""
    text = para["text"]

    closed_matches = list(QUOTE_RE.finditer(text))
    unclosed_match = UNCLOSED_QUOTE_RE.search(text) if not closed_matches else None

    if not closed_matches and not unclosed_match:
        return False

    if para["type"] == "narration":
        return True

    if para["type"] == "dialogue" and closed_matches:
        quoted_len = sum(len(_quote_text(m)) for m in closed_matches)
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
    """Split mixed paragraphs into narration + dialogue parts and re-index."""
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

        db.query(DBParagraph).filter(DBParagraph.chapter_id == ch.id).delete()
        db.flush()

        for i, p in enumerate(new_paras):
            db.add(DBParagraph(
                chapter_id=ch.id,
                scene_id=None,
                index=i,
                text=p["text"],
                type=p["type"],
                speaker=p.get("speaker") if p["type"] == "dialogue" else None,
            ))

        print(f"  [{ch.chapter_id}] {ch.title[:50]:<50} {len(db_paras)} -> {len(new_paras)}  (+{splits} splits)")

    db.commit()
    print("Quote splitting done.")