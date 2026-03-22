"""
LLM zero-shot dialogue attribution.

Берёт параграфы чанками по N, отправляет в Claude Haiku,
просит определить speaker для каждой реплики (dialogue).
Результат пишет в поле speaker_llm_zeroshot.
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

SYSTEM_PROMPT = """\
You are an expert literary analyst specializing in dialogue attribution.
You will receive numbered paragraphs from a novel.

Your task: for EVERY paragraph return its index and type.
For DIALOGUE paragraphs also identify the speaker.

Rules:
- Use character name exactly as it appears in text
- If speaker cannot be determined, return null
- Return ONLY valid JSON, no explanation

Output format:
[
  {"index": 0, "type": "narration", "speaker": null},
  {"index": 1, "type": "dialogue", "speaker": "Alice"},
  ...
]
"""


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
) -> dict[int, str | None]:
    user_msg = _build_user_message(chunk, offset)

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
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


def run_zeroshot(
    input_path: str,
    output_path: str,
    chapter_idx: int = 0,
    chunk_size: int = CHUNK_SIZE,
) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    client = anthropic.Anthropic(api_key=api_key)

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    chapter = data["chapters"][chapter_idx]
    paragraphs = chapter["paragraphs"]
    total = len(paragraphs)

    print(f"Глава [{chapter_idx}]: {chapter['title']}")
    print(f"Параграфов: {total}  |  чанков: {(total + chunk_size - 1) // chunk_size}")
    print(f"Модель: {MODEL}\n")

    for p in paragraphs:
        p["speaker_llm_zeroshot"] = None

    dialogue_indices = [i for i, p in enumerate(paragraphs) if p["type"] == "dialogue"]
    print(f"Диалоговых параграфов: {len(dialogue_indices)}\n")

    for chunk_start in range(0, total, chunk_size):
        chunk = paragraphs[chunk_start: chunk_start + chunk_size]
        chunk_num = chunk_start // chunk_size + 1
        total_chunks = (total + chunk_size - 1) // chunk_size

        print(f"Чанк {chunk_num}/{total_chunks}  (параграфы {chunk_start}–{chunk_start + len(chunk) - 1})")

        attributions = attribute_chunk(client, chunk, offset=chunk_start)

        for idx, speaker in attributions.items():
            paragraphs[idx]["speaker_llm_zeroshot"] = speaker

        attributed = sum(1 for v in attributions.values() if v is not None)
        print(f"  → атрибутировано {attributed}/{len(attributions)} реплик")

        if chunk_start + chunk_size < total:
            time.sleep(0.5)

    print("\n" + "=" * 50)
    print("СТАТИСТИКА")
    print("=" * 50)

    total_dialogue = len(dialogue_indices)
    llm_attributed = sum(
        1 for i in dialogue_indices
        if paragraphs[i]["speaker_llm_zeroshot"] is not None
    )
    booknlp_attributed = sum(
        1 for i in dialogue_indices
        if paragraphs[i].get("speaker") is not None
    )

    both = [
        i for i in dialogue_indices
        if paragraphs[i].get("speaker") is not None
        and paragraphs[i]["speaker_llm_zeroshot"] is not None
    ]
    match = sum(
        1 for i in both
        if paragraphs[i]["speaker"].strip().lower()
        == paragraphs[i]["speaker_llm_zeroshot"].strip().lower()
    )

    print(f"Всего диалогов:              {total_dialogue}")
    print(f"BookNLP атрибутировал:       {booknlp_attributed}")
    print(f"LLM zero-shot атрибутировал: {llm_attributed}")
    print(f"Оба дали ответ:              {len(both)}")
    print(f"Совпадений:                  {match}  ({match/len(both)*100:.1f}% от обоих)" if both else "Совпадений: —")
    print(f"Расхождений:                 {len(both) - match}")

    if both:
        print("\nПримеры расхождений:")
        shown = 0
        for i in both:
            if paragraphs[i]["speaker"].strip().lower() != paragraphs[i]["speaker_llm_zeroshot"].strip().lower():
                print(f"  [{i}] BookNLP={paragraphs[i]['speaker']!r:20}  LLM={paragraphs[i]['speaker_llm_zeroshot']!r}")
                print(f"       {paragraphs[i]['text'][:80]}...")
                shown += 1
                if shown >= 5:
                    break

    # ── Сохраняем ────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tmp = output_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=True, indent=2))
    os.replace(tmp, output_path)

    print(f"\nСохранено: {output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("book", help="Имя книги, например: alice, pride_prejudice")
    parser.add_argument("--chapter", type=int, default=None, help="Индекс одной главы")
    parser.add_argument("--all-chapters", action="store_true", help="Обработать все главы")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--input",  default=None, help="Входной JSON (по умолчанию parsed_final.json)")
    parser.add_argument("--output", default=None, help="Выходной JSON (по умолчанию parsed_llm_zeroshot.json)")
    args = parser.parse_args()

    if not args.all_chapters and args.chapter is None:
        parser.error("Укажи --chapter N или --all-chapters")

    base = f"storage/uploads/{args.book}"
    input_path = args.input  or f"{base}/parsed_final.json"
    output_path = args.output or f"{base}/parsed_llm_zeroshot.json"

    if args.all_chapters:
        with open(input_path, encoding="utf-8") as f:
            data = json.load(f)
        total_chapters = len(data["chapters"])
        for idx in range(total_chapters):
            # Пропускаем главы где LLM уже отработал
            paras = data["chapters"][idx]["paragraphs"]
            dialogues = [p for p in paras if p["type"] == "dialogue"]
            done = sum(1 for p in dialogues if p.get("speaker_llm_zeroshot") is not None)
            if dialogues and done >= len(dialogues) * 0.8:
                print(f"\nГЛАВА {idx}/{total_chapters-1} — пропускаем (уже обработана, {done}/{len(dialogues)})")
                continue
            print(f"\n{'='*50}")
            print(f"ГЛАВА {idx}/{total_chapters - 1}")
            print(f"{'='*50}")
            src = output_path if idx > 0 and os.path.exists(output_path) else input_path
            run_zeroshot(src, output_path, chapter_idx=idx, chunk_size=args.chunk_size)
            # Перечитываем data после сохранения
            with open(output_path, encoding="utf-8") as f:
                data = json.load(f)
    else:
        run_zeroshot(input_path, output_path, chapter_idx=args.chapter, chunk_size=args.chunk_size)