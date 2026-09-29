"""Audit frozen gold-span containment after a Round 4 retrieval run.

This is a mechanical diagnostic: it does not assess claim semantics, absent
evidence, visual table meaning, or harmful mismatches.  It deliberately opens
gold only after ``round4_eval.py run`` has completed.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def contains(evidence: dict, span: dict) -> bool:
    locator = evidence["locator"]
    return (
        locator["page"] == span["page"]
        and locator["char_start"] <= span["start"]
        and locator["char_end"] >= span["end"]
    )


def audit(run: dict, gold: dict) -> dict:
    if not run.get("complete"):
        raise ValueError("Run is incomplete")
    by_intent = {case["intent_id"]: case for case in gold["cases"]}
    rows = []
    for row in run["rows"]:
        if row["repetition"] != 1:
            continue
        case = by_intent[row["intent_id"]]
        spans = {span["span_id"]: span for span in case["spans"]}
        evidence = row.get("evidence", [])
        requirements = {
            requirement["requirement_id"]: all(
                any(contains(item, spans[span_id]) for item in evidence)
                for span_id in requirement["span_ids"]
            )
            for requirement in case["requirements"]
        }
        sufficient = case["reference_verdict"] != "insufficient" and any(
            all(requirements[requirement_id] for requirement_id in group)
            for group in case["sufficient_sets"]
        )
        rows.append(
            {
                "intent_id": row["intent_id"],
                "paper_id": row["paper_id"],
                "language": row["language"],
                "policy": row["policy"],
                "reference_verdict": case["reference_verdict"],
                "requirements": requirements,
                "full_minimal_set": sufficient,
                "replay_integrity": row["replay_integrity"],
                "budget_ok": row.get("budget_ok", False),
            }
        )
    summary: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(dict))
    for language in sorted({row["language"] for row in rows}):
        for policy in sorted({row["policy"] for row in rows}):
            subset = [
                row for row in rows if row["language"] == language and row["policy"] == policy
            ]
            answerable = [row for row in subset if row["reference_verdict"] != "insufficient"]
            summary[language][policy] = {
                "answerable": len(answerable),
                "full_minimal_set": sum(row["full_minimal_set"] for row in answerable),
                "all_replay_integrity": all(row["replay_integrity"] for row in subset),
                "all_budget_ok": all(row["budget_ok"] for row in subset),
            }
    return {
        "kind": "round4_exact_span_coverage",
        "warning": "Mechanical exact-span containment only; not semantic ESR or promotion evidence.",
        "rows": rows,
        "summary": summary,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(read(args.run), read(args.gold))
    write(args.output, report)
    for language, policies in report["summary"].items():
        for policy, result in policies.items():
            print(language, policy, result["full_minimal_set"], "/", result["answerable"])


if __name__ == "__main__":
    main()
