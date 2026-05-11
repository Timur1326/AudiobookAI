"""
Dialogue attribution evaluation: LLM context method vs ground truth.

Usage:
    python evaluate_attribution.py alice
    python evaluate_attribution.py alice --by-chapter
    python evaluate_attribution.py alice --by-character
    python evaluate_attribution.py pride_prejudice --gt storage/uploads/pride_prejudice/ground_truth.json
"""

import argparse
import json
from dataclasses import dataclass


@dataclass
class Stats:
    total_gt: int = 0
    attributed: int = 0
    correct: int = 0

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
        self.total_gt += other.total_gt
        self.attributed += other.attributed
        self.correct += other.correct
        return self


def norm(name: str | None) -> str:
    return name.strip().lower() if name else ""


def evaluate_chapter(paragraphs: list[dict]) -> Stats:
    s = Stats()
    for p in paragraphs:
        if p["type"] != "dialogue":
            continue
        gt = norm(p.get("speaker_ground_truth"))
        if not gt:
            continue
        pred = norm(p.get("speaker_llm_context"))
        s.total_gt += 1
        if pred:
            s.attributed += 1
            if pred == gt:
                s.correct += 1
    return s


def print_row(label: str, s: Stats) -> None:
    print(f"  {label:<38} {s.total_gt:>4}  {s.attributed:>4}  {s.correct:>7}  "
          f"{s.precision:>6.1%}  {s.recall:>6.1%}  {s.f1:>6.1%}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("book", help="Book name, e.g. alice")
    parser.add_argument("--gt", default=None, help="Path to ground_truth.json (default: storage/uploads/<book>/ground_truth.json)")
    parser.add_argument("--by-chapter", action="store_true")
    parser.add_argument("--by-character", action="store_true")
    args = parser.parse_args()

    gt_path = args.gt or f"storage/uploads/{args.book}/ground_truth.json"
    with open(gt_path, encoding="utf-8") as f:
        data = json.load(f)

    print(f"\nBook:   {data.get('title', args.book)}")
    print(f"Method: LLM context (scene-level attribution with character list)\n")

    header = f"  {'Chapter' if args.by_chapter else '':<38} {'GT':>4}  {'Attr':>4}  {'Correct':>7}  {'Prec':>6}  {'Rec':>6}  {'F1':>6}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    book_stats = Stats()
    char_stats: dict[str, Stats] = {}

    for ch in data["chapters"]:
        ch_stats = evaluate_chapter(ch["paragraphs"])
        book_stats += ch_stats

        if args.by_chapter and ch_stats.total_gt > 0:
            title = ch.get("title", f"Chapter {ch['id']}")[:38]
            print_row(title, ch_stats)

        if args.by_character:
            for p in ch["paragraphs"]:
                if p["type"] != "dialogue":
                    continue
                gt = norm(p.get("speaker_ground_truth"))
                if not gt:
                    continue
                pred = norm(p.get("speaker_llm_context"))
                s = char_stats.setdefault(gt, Stats())
                s.total_gt += 1
                if pred:
                    s.attributed += 1
                    if pred == gt:
                        s.correct += 1

    print("  " + "=" * (len(header) - 2))
    print_row("TOTAL", book_stats)

    if args.by_character:
        print(f"\n  {'Character':<22} {'GT':>4}  {'Correct':>7}  {'Acc':>6}")
        print("  " + "-" * 40)
        for char, s in sorted(char_stats.items(), key=lambda x: -x[1].total_gt):
            if s.total_gt < 3:
                continue
            print(f"  {char:<22} {s.total_gt:>4}  {s.correct:>7}  {s.correct/s.total_gt:>6.1%}")


if __name__ == "__main__":
    main()