"""Audit exact-span recall after CiteFabric's default retrieval budget.

This is a post-hoc gold audit.  The input run must have been produced without
opening the gold fixture.  Candidates are selected in rank order using the
same single-paper limits as ``find_evidence``: at most four passages and 6,000
raw passage characters.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def contains(candidate: dict, span: dict) -> bool:
    return (
        candidate["unit_id"] == f"page:{span['page']}"
        and candidate["start"] <= span["start"]
        and candidate["end"] >= span["end"]
    )


def select_default_budget(candidates: list[dict]) -> tuple[list[dict], int]:
    selected = []
    size = 0
    for candidate in candidates:
        length = candidate["end"] - candidate["start"]
        if len(selected) >= 4 or size + length > 6000:
            continue
        selected.append(candidate)
        size += length
    return selected, size


def sufficient(selected: list[dict], case: dict) -> bool:
    spans = {span["span_id"]: span for span in case["spans"]}
    requirements = {
        requirement["requirement_id"]: all(
            any(contains(candidate, spans[span_id]) for candidate in selected)
            for span_id in requirement["span_ids"]
        )
        for requirement in case["requirements"]
    }
    return any(
        all(requirements[requirement_id] for requirement_id in sufficient_set)
        for sufficient_set in case["sufficient_sets"]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Output already exists")
    run = read(args.run)
    gold = {case["intent_id"]: case for case in read(args.gold)["cases"]}
    rows = []
    for result in run["rows"]:
        case = gold[result["intent_id"]]
        for arm, candidates in result["arms"].items():
            selected, selected_chars = select_default_budget(candidates)
            rows.append(
                {
                    "intent_id": result["intent_id"],
                    "paper_id": result["paper_id"],
                    "language": result["language"],
                    "arm": arm,
                    "selected_count": len(selected),
                    "selected_chars": selected_chars,
                    "reference_verdict": case["reference_verdict"],
                    "exact_span_recall": (
                        None
                        if case["reference_verdict"] == "insufficient"
                        else sufficient(selected, case)
                    ),
                }
            )
    summary = {}
    for language in sorted({row["language"] for row in rows}):
        summary[language] = {}
        for arm in sorted({row["arm"] for row in rows if row["language"] == language}):
            subset = [
                row
                for row in rows
                if row["language"] == language
                and row["arm"] == arm
                and row["reference_verdict"] != "insufficient"
            ]
            per_paper: dict[str, list[dict]] = defaultdict(list)
            for row in subset:
                per_paper[row["paper_id"]].append(row)
            summary[language][arm] = {
                "exact_span_recall": {
                    "numerator": sum(row["exact_span_recall"] for row in subset),
                    "denominator": len(subset),
                },
                "mean_selected_count": sum(row["selected_count"] for row in subset) / len(subset),
                "mean_selected_chars": sum(row["selected_chars"] for row in subset) / len(subset),
                "per_paper": {
                    paper: {
                        "numerator": sum(row["exact_span_recall"] for row in values),
                        "denominator": len(values),
                    }
                    for paper, values in sorted(per_paper.items())
                },
            }
            insufficient = [
                row
                for row in rows
                if row["language"] == language
                and row["arm"] == arm
                and row["reference_verdict"] == "insufficient"
            ]
            summary[language][arm]["insufficient_candidate_exposure"] = {
                "numerator": sum(row["selected_count"] > 0 for row in insufficient),
                "denominator": len(insufficient),
            }
    payload = {
        "kind": "round4_default_budget_exact_span_audit",
        "warning": (
            "Opened self-review development set. This simulates ranked seed selection only; "
            "it does not score context expansion, semantic accuracy, or insufficient-claim safety."
        ),
        "budget": {"max_chars": 6000, "max_passages_per_paper": 4},
        "source_run": str(args.run),
        "rows": rows,
        "summary": summary,
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
