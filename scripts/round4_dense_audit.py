"""Post-hoc exact-span recall audit for a gold-blind dense candidate run."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

K_VALUES = (1, 3, 6, 12, 48)


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def contains(candidate: dict, span: dict) -> bool:
    return (
        candidate["unit_id"] == f"page:{span['page']}"
        and candidate["start"] <= span["start"]
        and candidate["end"] >= span["end"]
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
        if case["reference_verdict"] == "insufficient":
            continue
        spans = {span["span_id"]: span for span in case["spans"]}
        for arm, candidates in result["arms"].items():
            recall = {}
            for k in K_VALUES:
                subset = candidates[:k]
                requirements = {
                    requirement["requirement_id"]: all(
                        any(contains(candidate, spans[span_id]) for candidate in subset)
                        for span_id in requirement["span_ids"]
                    )
                    for requirement in case["requirements"]
                }
                recall[str(k)] = any(
                    all(requirements[requirement_id] for requirement_id in sufficient_set)
                    for sufficient_set in case["sufficient_sets"]
                )
            rows.append(
                {
                    "intent_id": result["intent_id"],
                    "paper_id": result["paper_id"],
                    "language": result["language"],
                    "arm": arm,
                    "recall": recall,
                }
            )
    summary = {}
    for language in ("en", "zh"):
        summary[language] = {}
        for arm in sorted({row["arm"] for row in rows if row["language"] == language}):
            subset = [row for row in rows if row["language"] == language and row["arm"] == arm]
            per_paper: dict[str, list[dict]] = defaultdict(list)
            for row in subset:
                per_paper[row["paper_id"]].append(row)
            summary[language][arm] = {
                "recall_at_k": {
                    str(k): {
                        "numerator": sum(row["recall"][str(k)] for row in subset),
                        "denominator": len(subset),
                    }
                    for k in K_VALUES
                },
                "per_paper_at_6": {
                    paper: {
                        "numerator": sum(row["recall"]["6"] for row in values),
                        "denominator": len(values),
                    }
                    for paper, values in sorted(per_paper.items())
                },
            }
    arms = {row["arm"] for row in rows}
    if {"lexical_v2_candidates", "lexical_dense_rrf_candidates"} <= arms:
        route_rows = [
            row
            for row in rows
            if row["arm"]
            == (
                "lexical_v2_candidates"
                if row["language"] == "en"
                else "lexical_dense_rrf_candidates"
            )
        ]
        summary["language_route"] = {
            "recall_at_k": {
                str(k): {
                    "numerator": sum(row["recall"][str(k)] for row in route_rows),
                    "denominator": len(route_rows),
                }
                for k in K_VALUES
            }
        }
    payload = {
        "kind": "round4_multilingual_dense_exact_span_audit",
        "warning": (
            "Opened self-review development set. Candidate exact-span recall is not selected "
            "evidence sufficiency, semantic accuracy, or insufficient-claim safety."
        ),
        "model": run["model"],
        "rows": rows,
        "summary": summary,
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
