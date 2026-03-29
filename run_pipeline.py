"""
Full pipeline: from EPUB to synthesized audiobook.

Steps:
  1. Parse EPUB              → parsed.json
  2. Split quotes            → parsed_final.json
  3. Attribute dialogue      → parsed_final.json (speaker field)
  4. Split into scenes       → parsed_with_scenes.json
  5. Extract characters      → characters.json
  6. Assign voices           → voice_map_elevenlabs.json
  7. Synthesize TTS          → audio/chapter_XX.mp3

Usage:
    python run_pipeline.py alice
    python run_pipeline.py alice --steps 1 2 3
    python run_pipeline.py alice --from 4
    python run_pipeline.py alice --engine xtts --chapter 0
"""

import argparse
import json
import time
from pathlib import Path

STORAGE_DIR   = Path("storage/uploads")
DATASETS_DIR  = Path("experiments/datasets")


def step_header(n: int, title: str) -> None:
    print(f"\n{'='*55}")
    print(f"  Step {n}: {title}")
    print(f"{'='*55}")


# ── Step 1: Parse EPUB ────────────────────────────────────────

def step_parse(book: str, epub_path: Path) -> None:
    from core.parser.epub_parser import parse_epub, save_to_json
    out = STORAGE_DIR / book / "parsed.json"
    if out.exists():
        print(f"  Already exists: {out.name} — skipping")
        return
    b = parse_epub(str(epub_path))
    save_to_json(b, str(out))
    print(f"  Saved: {out.name}  ({len(b.chapters)} chapters)")


# ── Step 2: Split quotes ──────────────────────────────────────

def step_quotes(book: str) -> None:
    from core.nlp.quote_splitter import run as quote_run
    out = STORAGE_DIR / book / "parsed_final.json"
    if out.exists():
        print(f"  Already exists: {out.name} — skipping")
        return
    quote_run(book)


# ── Step 3: Attribute dialogue ────────────────────────────────

def step_attribute(book: str, attributor: str) -> None:
    base = STORAGE_DIR / book
    out  = base / "parsed_final.json"

    with open(out, encoding="utf-8") as f:
        data = json.load(f)

    already = sum(
        1 for ch in data["chapters"]
        for p in ch["paragraphs"]
        if p.get("type") == "dialogue" and p.get("speaker_llm_context")
    )
    if already > 0:
        print(f"  Already attributed ({already} lines) — skipping")
        return

    if attributor == "context":
        from core.nlp.llm_attributor_with_context import run as attr_run
        attr_run(book)
    else:
        from core.nlp.llm_attributor import run as attr_run
        attr_run(book)


# ── Step 4: Split into scenes ─────────────────────────────────

def step_scenes(book: str) -> None:
    from core.audio.scene_splitter import run as scene_run
    out = STORAGE_DIR / book / "parsed_with_scenes.json"
    if out.exists():
        print(f"  Already exists: {out.name} — skipping")
        return
    scene_run(book)


# ── Step 5: Extract characters ────────────────────────────────

def step_characters(book: str) -> None:
    from core.nlp.character_extractor import run as char_run
    out = STORAGE_DIR / book / "characters.json"
    if out.exists():
        print(f"  Already exists: {out.name} — skipping")
        return
    char_run(book)


# ── Step 6: Assign voices ─────────────────────────────────────

def step_voices(book: str) -> None:
    from core.nlp.voice_assigner import run as voice_run
    out = STORAGE_DIR / book / "voice_map_elevenlabs.json"
    if out.exists():
        print(f"  Already exists: {out.name} — skipping")
        return
    voice_run(book)


# ── Step 7: Synthesize TTS ────────────────────────────────────

def step_synthesize(book: str, engine: str, chapter: int | None) -> None:
    import synthesize_chapter as sc

    base = STORAGE_DIR / book
    with open(base / "parsed_with_scenes.json", encoding="utf-8") as f:
        data = json.load(f)

    chapters = data["chapters"]
    targets  = [chapters[chapter]] if chapter is not None else chapters
    vm       = sc.load_voice_map(book, engine)

    for ch in targets:
        ch_idx = next(i for i, c in enumerate(chapters) if c["id"] == ch["id"])
        print(f"\n  Chapter [{ch['id']}] {ch['title'][:50]}")
        sc.synthesize_chapter(book, ch_idx, engine, vm, use_voice_map=True)


# ── Main ──────────────────────────────────────────────────────

ALL_STEPS = [1, 2, 3, 4, 5, 6, 7]

STEP_NAMES = {
    1: "Parse EPUB",
    2: "Split quotes",
    3: "Attribute dialogue",
    4: "Split into scenes",
    5: "Extract characters",
    6: "Assign voices",
    7: "Synthesize TTS",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("book",         help="Book name, e.g.: alice")
    parser.add_argument("--epub",       default=None, help="Path to EPUB (default: experiments/datasets/{book}.epub)")
    parser.add_argument("--steps",      nargs="+", type=int, default=None, help="Run only these steps, e.g. --steps 1 2")
    parser.add_argument("--from",      dest="from_step", type=int, default=None, help="Run from this step to the end")
    parser.add_argument("--engine",     default="elevenlabs", choices=["elevenlabs", "azure", "xtts"])
    parser.add_argument("--chapter",    type=int, default=None, help="Synthesize only this chapter (step 7)")
    parser.add_argument("--attributor", default="context", choices=["context", "zeroshot"])
    args = parser.parse_args()

    epub_path = Path(args.epub) if args.epub else DATASETS_DIR / f"{args.book}.epub"

    if args.steps:
        steps = sorted(args.steps)
    elif args.from_step:
        steps = [s for s in ALL_STEPS if s >= args.from_step]
    else:
        steps = ALL_STEPS

    print(f"Book:    {args.book}")
    print(f"Steps:   {steps}")
    print(f"Engine:  {args.engine}")

    t0 = time.time()

    for s in steps:
        step_header(s, STEP_NAMES[s])
        if s == 1:
            step_parse(args.book, epub_path)
        elif s == 2:
            step_quotes(args.book)
        elif s == 3:
            step_attribute(args.book, args.attributor)
        elif s == 4:
            step_scenes(args.book)
        elif s == 5:
            step_characters(args.book)
        elif s == 6:
            step_voices(args.book)
        elif s == 7:
            step_synthesize(args.book, args.engine, args.chapter)

    print(f"\n{'='*55}")
    print(f"  Done in {time.time() - t0:.1f}s")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()