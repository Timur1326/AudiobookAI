"""
Post-processing: разбивает смешанные параграфы (dialogue внутри narration)
на отдельные куски используя regex для кавычек и spaCy NER для спикера.

Запуск:
    python -m core.nlp.quote_splitter alice
    python -m core.nlp.quote_splitter alice --input parsed_final.json --output parsed_fixed.json
    python -m core.nlp.quote_splitter alice --chapter 11 --preview
"""

import json
import re
from pathlib import Path

import spacy

# Закрытые кавычки: "текст"
QUOTE_RE = re.compile(r'["\u201c](.*?)["\u201d]', re.DOTALL)

# Незакрытая кавычка до конца строки: ..."текст до конца
UNCLOSED_QUOTE_RE = re.compile(r'["\u201c\\"](.*?)$', re.DOTALL)

nlp = None  # загружаем лениво


def get_nlp():
    global nlp
    if nlp is None:
        nlp = spacy.load("en_core_web_sm")
    return nlp


def find_speaker(context: str, known_speakers: set[str]) -> str | None:
    """
    Найти спикера в тексте attribution.
    1. Сначала ищем среди известных персонажей книги (точное совпадение)
    2. Затем spaCy NER — любая PERSON сущность
    """
    if not context.strip():
        return None

    context_lower = context.lower()

    # Быстрый поиск среди известных персонажей
    for name in known_speakers:
        if name.lower() in context_lower:
            return name

    # spaCy NER как fallback
    doc = get_nlp()(context)
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            return ent.text.strip()

    return None


def split_paragraph(para: dict, known_speakers: set[str]) -> list[dict]:
    """
    Разбить параграф на части по кавычкам.
    Возвращает список параграфов (исходный если разбивать не нужно).
    """
    text = para["text"]
    matches = list(QUOTE_RE.finditer(text))

    # Если нет закрытых кавычек — ищем незакрытую
    if not matches:
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
            speaker = para.get("speaker_ground_truth") or para.get("speaker")
        parts.append(_make_para(para, quote, "dialogue", speaker))
        return parts if len(parts) > 1 else [para]

    parts = []
    cursor = 0

    for m in matches:
        before = text[cursor:m.start()].strip().strip('",;: ')
        quote  = m.group(1).strip()
        cursor = m.end()
        after_peek = text[cursor:cursor + 100]

        # Текст до кавычки → narration
        if len(before) > 3:
            parts.append(_make_para(para, before, "narration", None))

        # Кавычка → dialogue, ищем спикера в before и after
        if len(quote) > 1:
            speaker = (
                find_speaker(before, known_speakers) or
                find_speaker(after_peek, known_speakers)
            )
            # Если параграф уже был dialogue с известным спикером — сохраняем
            if not speaker and para["type"] == "dialogue":
                speaker = para.get("speaker_ground_truth") or para.get("speaker")
            parts.append(_make_para(para, quote, "dialogue", speaker))

    # Остаток после последней кавычки → narration
    after = text[cursor:].strip().strip('",;: ')
    if len(after) > 3:
        parts.append(_make_para(para, after, "narration", None))

    # Если разбивка не дала смысла — возвращаем оригинал
    if len(parts) <= 1:
        return [para]

    return parts


def _make_para(source: dict, text: str, ptype: str, speaker: str | None) -> dict:
    return {
        "text":                  text,
        "type":                  ptype,
        "chapter_id":            source["chapter_id"],
        "speaker":               speaker if ptype == "dialogue" else None,
        "scene":                 source.get("scene"),
        "speaker_llm_zeroshot":  None,
        "speaker_llm_context":   None,
        "speaker_ground_truth":  speaker if ptype == "dialogue" else None,
    }


def _needs_splitting(para: dict) -> bool:
    """True если параграф содержит кавычки которые стоит разбить."""
    text = para["text"]

    closed_matches = list(QUOTE_RE.finditer(text))
    unclosed_match = UNCLOSED_QUOTE_RE.search(text) if not closed_matches else None

    if not closed_matches and not unclosed_match:
        return False

    # Narration с любыми кавычками — разбиваем
    if para["type"] == "narration":
        return True

    # Dialogue где кавычки занимают меньше 85% текста (есть attribution снаружи)
    if para["type"] == "dialogue" and closed_matches:
        quoted_len = sum(len(m.group(1)) for m in closed_matches)
        return quoted_len < len(text) * 0.85

    return False


def collect_speakers(data: dict) -> set[str]:
    """Собрать известных спикеров — только реальные имена персонажей."""
    speakers = set()
    for ch in data["chapters"]:
        for p in ch["paragraphs"]:
            s = p.get("speaker_ground_truth") or p.get("speaker")
            if not s:
                continue
            s = s.strip()
            # Фильтруем мусор: только строки из букв/пробелов, длина 2-30
            if 2 <= len(s) <= 30 and re.match(r"^[A-Za-z][A-Za-z '\-]+$", s):
                speakers.add(s)
    return speakers


def process_book(data: dict, chapter_idx: int | None, preview: bool) -> dict:
    known_speakers = collect_speakers(data)
    print(f"Известных персонажей: {len(known_speakers)}: {', '.join(sorted(known_speakers))}\n")

    chapters = (
        [data["chapters"][chapter_idx]] if chapter_idx is not None
        else data["chapters"]
    )

    total_before = total_after = 0

    for ch in chapters:
        old_paras = ch["paragraphs"]
        new_paras = []
        splits_in_chapter = 0

        for para in old_paras:
            if _needs_splitting(para):
                result = split_paragraph(para, known_speakers)
                if len(result) > 1:
                    splits_in_chapter += 1
                    if preview:
                        print(f"  SPLIT [{para['type']}]: {para['text'][:80]}...")
                        for r in result:
                            print(f"    → [{r['type']}] ({r['speaker'] or 'narrator'}) {r['text'][:60]}")
                        print()
                new_paras.extend(result)
            else:
                new_paras.append(para)

        before = len(old_paras)
        after  = len(new_paras)
        total_before += before
        total_after  += after
        diff = after - before

        print(f"[{ch['id']}] {ch['title'][:55]:<55} {before} → {after}  (+{diff}, {splits_in_chapter} разбито)")

        if not preview:
            ch["paragraphs"]       = new_paras
            ch["total_paragraphs"] = after

    return data


def run(
    book: str,
    input_file: str  = "parsed_final.json",
    output_file: str = "parsed_fixed.json",
    chapter_idx: int | None = None,
    preview: bool = False,
) -> None:
    base = Path(f"storage/uploads/{book}")
    input_path  = base / input_file
    output_path = base / output_file

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    print(f"Книга:  {data['title']}")
    print(f"Глав:   {len(data['chapters'])}")
    print(f"Режим:  {'PREVIEW (не сохраняем)' if preview else 'WRITE'}\n")

    data = process_book(data, chapter_idx, preview)

    if not preview:
        tmp = str(output_path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=True, indent=2))
        import os; os.replace(tmp, output_path)
        print(f"\nСохранено: {output_path}")
    else:
        print("\nPreview завершён. Запусти без --preview чтобы сохранить.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("book",      help="Имя книги, например: alice")
    parser.add_argument("--input",   default="parsed_final.json")
    parser.add_argument("--output",  default="parsed_fixed.json")
    parser.add_argument("--chapter", type=int, default=None)
    parser.add_argument("--preview", action="store_true",
                        help="Показать что будет разбито без сохранения")
    args = parser.parse_args()

    run(args.book, args.input, args.output, args.chapter, args.preview)