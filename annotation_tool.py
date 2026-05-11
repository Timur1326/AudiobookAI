"""
Handy tool for annotating dialogue speakers in the parsed JSON. It shows the dialogue line, LLM predictions, and some context, and allows the user to input the correct speaker.

Usage:
    python annotation_tool.py alice
    python annotation_tool.py alice --chapter 0
    python annotation_tool.py alice --reset
"""

import argparse
import json
import os
import sys


def load_data(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict, path: str) -> None:
    serialized = json.dumps(data, ensure_ascii=True, indent=2)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(serialized)
    os.replace(tmp, path)


def print_context(paragraphs: list[dict], current_idx: int, window: int = 3) -> None:
    start = max(0, current_idx - window)
    print()
    for i in range(start, current_idx):
        p = paragraphs[i]
        prefix = "  [narr]" if p["type"] == "narration" else f"  [{p.get('speaker','?')}]"
        print(f"\033[90m{prefix} {p['text'][:120]}\033[0m")


def print_dialogue(p: dict, idx: int, total: int, done: int) -> None:
    print()
    print(f"\033[1m[{idx}]  ({done} готово)\033[0m")
    print(f"\033[97m  \"{p['text']}\"\033[0m")
    print()
    booknlp = p.get("speaker") or "—"
    llm_z   = p.get("speaker_llm_zeroshot") or "—"
    llm_c   = p.get("speaker_llm_context") or "—"
    gt      = p.get("speaker_ground_truth")

    print(f"  BookNLP    : \033[33m{booknlp}\033[0m")
    print(f"  LLM zero   : \033[36m{llm_z}\033[0m")
    print(f"  LLM context: \033[32m{llm_c}\033[0m")
    if gt:
        print(f"  Ground truth is entered: \033[35m{gt}\033[0m")


def get_input(llm_context: str | None) -> str | None:
    default = llm_context or "?"
    try:
        raw = input(f"\n  Speaker [Enter={default} | s=skip | q=quit]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return "__quit__"

    if raw.lower() == "q":
        return "__quit__"
    if raw.lower() == "s":
        return "__skip__"
    if raw == "":
        return llm_context
    return raw


def merge_ground_truth(data: dict, saved_path: str) -> None:
    if not os.path.exists(saved_path):
        return
    try:
        saved = load_data(saved_path)
    except Exception:
        return
    for ch_idx, ch in enumerate(data["chapters"]):
        if ch_idx >= len(saved["chapters"]):
            break
        saved_paras = saved["chapters"][ch_idx]["paragraphs"]
        for p_idx, p in enumerate(ch["paragraphs"]):
            if p_idx >= len(saved_paras):
                break
            gt = saved_paras[p_idx].get("speaker_ground_truth")
            if gt is not None:
                p["speaker_ground_truth"] = gt


def annotate(
    input_path: str,
    output_path: str,
    chapter_idx: int | None,
    reset: bool,
) -> None:
    data = load_data(input_path)

    if not reset and input_path != output_path:
        merge_ground_truth(data, output_path)
    chapters = data["chapters"]

    chapter_range = (
        range(len(chapters)) if chapter_idx is None
        else range(chapter_idx, chapter_idx + 1)
    )

    for ch_idx in chapter_range:
        chapter = chapters[ch_idx]
        paragraphs = chapter["paragraphs"]
        dialogue_indices = [
            i for i, p in enumerate(paragraphs)
            if p["type"] == "dialogue"
        ]

        if not dialogue_indices:
            continue

        already_done = [
            i for i in dialogue_indices
            if paragraphs[i].get("speaker_ground_truth") is not None
        ]

        if reset:
            for i in dialogue_indices:
                paragraphs[i]["speaker_ground_truth"] = None
            already_done = []

        pending = [i for i in dialogue_indices if paragraphs[i].get("speaker_ground_truth") is None]

        print(f"\n{'='*60}")
        print(f"Chapter [{ch_idx}]: {chapter['title']}")
        print(f"Dialogues: {len(dialogue_indices)}  |  is ready: {len(already_done)}  |  remaining: {len(pending)}")
        print(f"{'='*60}")
        print("  Enter = accept LLM context | s = skip | q = exit")

        for i, para_idx in enumerate(pending):
            p = paragraphs[para_idx]
            print_context(paragraphs, para_idx)
            print_dialogue(p, para_idx, len(dialogue_indices), len(already_done) + i)

            result = get_input(p.get("speaker_llm_context"))

            if result == "__quit__":
                save_data(data, output_path)
                print(f"\nSave and exit : {output_path}")
                sys.exit(0)
            elif result == "__skip__":
                continue
            else:
                p["speaker_ground_truth"] = result

            save_data(data, output_path)

        done_now = sum(1 for i in dialogue_indices if paragraphs[i].get("speaker_ground_truth") is not None)
        print(f"\nChapter [{ch_idx}] is ready: {done_now}/{len(dialogue_indices)} annotated.")

    print(f"\n{'='*60}")
    print("TOTAL  BY BOOK")
    print(f"{'='*60}")
    total_d = total_gt = 0
    for ch in chapters:
        for p in ch["paragraphs"]:
            if p["type"] == "dialogue":
                total_d += 1
                if p.get("speaker_ground_truth") is not None:
                    total_gt += 1
    print(f"Total number of dialogues:    {total_d}")
    print(f"Annotated:      {total_gt}  ({total_gt/total_d*100:.1f}%)" if total_d else "")
    print(f"Remaining:          {total_d - total_gt}")
    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("book", help="Name of the book, e.g. alice")
    parser.add_argument("--chapter", type=int, default=None, help="Just one chapter index ")
    parser.add_argument("--input", default=None, help="Path to input JSON")
    parser.add_argument("--output", default=None, help="Save path for output JSON")
    parser.add_argument("--reset", action="store_true", help="Reset all existing annotations in the chapter")
    args = parser.parse_args()

    base = f"storage/uploads/{args.book}"
    input_path  = args.input  or f"{base}/parsed_llm_context.json"
    output_path = args.output or input_path

    if not os.path.exists(input_path):
        print(f"File not found: {input_path}")
        sys.exit(1)

    annotate(input_path, output_path, args.chapter, args.reset)