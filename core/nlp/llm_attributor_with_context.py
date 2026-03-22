"""
LLM attribution with character context.

Отличие от llm_attributor.py (zero-shot):
- Перед обработкой извлекаем всех уникальных персонажей из parsed_final.json
  (по полю speaker по всей книге) и добавляем в system prompt.
- Результат пишет в поле speaker_llm_context.
- Статистика: сравнение с BookNLP и с zero-shot (parsed_llm_zeroshot.json).
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
    """Собрать всех уникальных персонажей по полю speaker по всей книге."""
    seen: set[str] = set()
    for chapter in data["chapters"]:
        for para in chapter["paragraphs"]:
            speaker = para.get("speaker")
            if speaker and speaker.strip():
                seen.add(speaker.strip())
    return sorted(seen)


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
        raise ValueError("JSON-массив не найден в ответе")
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
            print(f"    [попытка {attempt}/{RETRY_LIMIT}] невалидный JSON: {e}")
            if attempt == RETRY_LIMIT:
                print("    Пропускаем чанк — возвращаем null для всех реплик")
                return {
                    offset + i: None
                    for i, p in enumerate(chunk)
                    if p["type"] == "dialogue"
                }
            time.sleep(1)

        except anthropic.RateLimitError:
            wait = 5 * attempt
            print(f"    Rate limit — ждём {wait}s...")
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
        print(f"{label_a} vs {label_b}: нет данных для сравнения")
        return

    match = sum(
        1 for i in both
        if paragraphs[i][field_a].strip().lower()
        == paragraphs[i][field_b].strip().lower()
    )
    print(f"\n{label_a} vs {label_b}:")
    print(f"  Оба дали ответ:  {len(both)}")
    print(f"  Совпадений:      {match}  ({match / len(both) * 100:.1f}%)")
    print(f"  Расхождений:     {len(both) - match}")

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
        raise ValueError("ANTHROPIC_API_KEY не задан в .env")

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
        print(f"Zero-shot данные загружены: {zeroshot_path}")
    else:
        print(f"Zero-shot файл не найден ({zeroshot_path}) — сравнение с zero-shot пропускается")

    # Извлекаем персонажей по всей книге
    characters = extract_characters(data)
    print(f"\nИзвлечено персонажей: {len(characters)}")
    print(f"  {', '.join(characters)}\n")

    system_prompt = _build_system_prompt(characters)

    chapter = data["chapters"][chapter_idx]
    paragraphs = chapter["paragraphs"]
    total = len(paragraphs)

    print(f"Глава [{chapter_idx}]: {chapter['title']}")
    print(f"Параграфов: {total}  |  чанков: {(total + chunk_size - 1) // chunk_size}")
    print(f"Модель: {MODEL}\n")

    # Инициализируем поле + копируем zero-shot для статистики
    for i, p in enumerate(paragraphs):
        p["speaker_llm_context"] = None
        if zeroshot_paragraphs:
            p["speaker_llm_zeroshot"] = zeroshot_paragraphs.get(i)

    dialogue_indices = [i for i, p in enumerate(paragraphs) if p["type"] == "dialogue"]
    print(f"Диалоговых параграфов: {len(dialogue_indices)}\n")

    # Обрабатываем чанками
    for chunk_start in range(0, total, chunk_size):
        chunk = paragraphs[chunk_start: chunk_start + chunk_size]
        chunk_num = chunk_start // chunk_size + 1
        total_chunks = (total + chunk_size - 1) // chunk_size

        print(f"Чанк {chunk_num}/{total_chunks}  (параграфы {chunk_start}–{chunk_start + len(chunk) - 1})")

        attributions = attribute_chunk(client, chunk, offset=chunk_start, system_prompt=system_prompt)

        for idx, speaker in attributions.items():
            paragraphs[idx]["speaker_llm_context"] = speaker

        attributed = sum(1 for v in attributions.values() if v is not None)
        print(f"  → атрибутировано {attributed}/{len(attributions)} реплик")

        if chunk_start + chunk_size < total:
            time.sleep(0.5)

    # ── Статистика ────────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("СТАТИСТИКА")
    print("=" * 50)

    total_dialogue = len(dialogue_indices)
    ctx_attributed = sum(
        1 for i in dialogue_indices if paragraphs[i]["speaker_llm_context"] is not None
    )
    booknlp_attributed = sum(
        1 for i in dialogue_indices if paragraphs[i].get("speaker") is not None
    )

    print(f"Всего диалогов:                  {total_dialogue}")
    print(f"BookNLP атрибутировал:           {booknlp_attributed}")
    print(f"LLM with-context атрибутировал:  {ctx_attributed}")

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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("book", help="Имя книги, например: alice, pride_prejudice")
    parser.add_argument("--chapter", type=int, default=None, help="Индекс одной главы")
    parser.add_argument("--all-chapters", action="store_true", help="Обработать все главы")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--input",    default=None, help="Входной JSON (по умолчанию parsed_final.json)")
    parser.add_argument("--zeroshot", default=None, help="Zero-shot JSON для сравнения")
    parser.add_argument("--output",   default=None, help="Выходной JSON (по умолчанию parsed_llm_context.json)")
    args = parser.parse_args()

    if not args.all_chapters and args.chapter is None:
        parser.error("Укажи --chapter N или --all-chapters")

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