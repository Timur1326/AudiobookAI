"""
Assessment of the quality of dialogue attribution.

Compare the predicted speaker (BookNLP, LLM zero-shot, LLM context) with the ground truth for each dialogue paragraph.

Usage:
    python evaluate.py alice
    python evaluate.py alice --chapter 0
    python evaluate.py alice --by-character
"""

import argparse
import json
from dataclasses import dataclass, field


@dataclass
class Stats:
    total_gt: int = 0
    attributed: int = 0
    correct: int = 0
    wrong: int = 0

    @property
    def precision(self) -> float:
        return self.correct / self.attributed if self.attributed else 0.0

    @property
    def recall(self) -> float:
        return self.correct / self.total_gt if self.total_gt else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def __iadd__(self, other: "Stats") -> "Stats":
        self.total_gt   += other.total_gt
        self.attributed += other.attributed
        self.correct    += other.correct
        self.wrong      += other.wrong
        return self


def norm(name: str | None) -> str:
    return name.strip().lower() if name else ""


def evaluate_paragraphs(paragraphs: list[dict]) -> dict[str, Stats]:
    models = {
        "BookNLP":      "speaker",
        "LLM zero-shot": "speaker_llm_zeroshot",
        "LLM context":  "speaker_llm_context",
    }
    stats = {name: Stats() for name in models}

    for p in paragraphs:
        if p["type"] != "dialogue":
            continue
        gt = norm(p.get("speaker_ground_truth"))
        if not gt:
            continue

        for model_name, field_key in models.items():
            s = stats[model_name]
            s.total_gt += 1
            pred = norm(p.get(field_key))
            if pred:
                s.attributed += 1
                if pred == gt:
                    s.correct += 1
                else:
                    s.wrong += 1

    return stats


def print_stats_table(stats: dict[str, Stats], title: str = "") -> None:
    if title:
        print(f"\n{title}")
    header = f"  {'Model':<20} {'GT':>5} {'Attr':>5} {'Correct':>8} {'Wrong':>6} {'Prec':>7} {'Rec':>7} {'F1':>7}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, s in stats.items():
        print(
            f"  {name:<20} {s.total_gt:>5} {s.attributed:>5} "
            f"{s.correct:>8} {s.wrong:>6} "
            f"{s.precision:>7.1%} {s.recall:>7.1%} {s.f1:>7.1%}"
        )


def print_errors(paragraphs: list[dict], model_field: str, model_name: str, limit: int = 5) -> None:
    shown = 0
    for p in paragraphs:
        if p["type"] != "dialogue":
            continue
        gt = norm(p.get("speaker_ground_truth"))
        pred = norm(p.get(model_field))
        if gt and pred and pred != gt:
            print(f"  GT={p['speaker_ground_truth']!r:<20} {model_name}={p[model_field]!r}")
            print(f"  → {p['text'][:90]}")
            shown += 1
            if shown >= limit:
                break


def evaluate_by_character(paragraphs: list[dict]) -> None:
    from collections import defaultdict
    char_stats: dict[str, Stats] = defaultdict(Stats)

    for p in paragraphs:
        if p["type"] != "dialogue":
            continue
        gt = norm(p.get("speaker_ground_truth"))
        if not gt:
            continue
        pred = norm(p.get("speaker_llm_context"))
        s = char_stats[gt]
        s.total_gt += 1
        if pred:
            s.attributed += 1
            if pred == gt:
                s.correct += 1
            else:
                s.wrong += 1

    print(f"\n  {'Character':<22} {'GT':>5} {'Correct':>8} {'Acc':>7}")
    print("  " + "-" * 46)
    for char, s in sorted(char_stats.items(), key=lambda x: -x[1].total_gt):
        if s.total_gt < 2:
            continue
        acc = s.correct / s.total_gt if s.total_gt else 0
        print(f"  {char:<22} {s.total_gt:>5} {s.correct:>8} {acc:>7.1%}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("book", help="Name of book, e.g. alice")
    parser.add_argument("--chapter", type=int, default=None, help="Just one chapter index")
    parser.add_argument("--by-character", action="store_true", help="Statistics by character")
    parser.add_argument("--errors", action="store_true", help="Show examples of errors")
    parser.add_argument("--input", default=None)
    args = parser.parse_args()

    path = args.input or f"storage/uploads/{args.book}/ground_truth.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    chapters = data["chapters"]

    print(f"\nBook: {data['title']}")
    print(f"Chapter:  {len(chapters)}")

    chapter_range = (
        [chapters[args.chapter]] if args.chapter is not None
        else chapters
    )

    book_stats: dict[str, Stats] = {
        "BookNLP":       Stats(),
        "LLM zero-shot": Stats(),
        "LLM context":   Stats(),
    }
    all_paragraphs: list[dict] = []

    print(f"\n{'='*70}")
    print("By chapter")
    print(f"{'='*70}")

    for ch in chapter_range:
        paras = ch["paragraphs"]
        gt_count = sum(1 for p in paras if p["type"] == "dialogue" and p.get("speaker_ground_truth"))
        if gt_count == 0:
            continue

        ch_stats = evaluate_paragraphs(paras)
        print_stats_table(ch_stats, title=f"  [{ch['id']}] {ch['title']}  (GT: {gt_count})")

        for k in book_stats:
            book_stats[k] += ch_stats[k]
        all_paragraphs.extend(paras)

    print(f"\n{'='*70}")
    print("Summary for the whole book")
    print(f"{'='*70}")
    print_stats_table(book_stats)

    if args.by_character:
        print(f"\n{'='*70}")
        print("Summary by character")
        print(f"{'='*70}")
        evaluate_by_character(all_paragraphs)

    if args.errors:
        for model_name, field_key in [
            ("BookNLP",       "speaker"),
            ("LLM zero-shot", "speaker_llm_zeroshot"),
            ("LLM context",   "speaker_llm_context"),
        ]:
            print(f"\n{'='*70}")
            print(f"Example of errors — {model_name}")
            print(f"{'='*70}")
            print_errors(all_paragraphs, field_key, model_name)


if __name__ == "__main__":
    main()