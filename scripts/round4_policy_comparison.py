"""Summarize exact-span coverage and cost for frozen Round 4 policy arms."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

ARMS = {
    "v2": {"en": "v2", "zh": "v2"},
    "structured_v3": {"en": "structured_v3", "zh": "structured_v3"},
    "offline_structured_v4": {
        "en": "offline_structured_v4",
        "zh": "offline_structured_v4",
    },
    "offline_structured_v5": {
        "en": "offline_structured_v5",
        "zh": "offline_structured_v5",
    },
    "offline_structured_v6": {
        "en": "offline_structured_v6",
        "zh": "offline_structured_v6",
    },
    "language_route": {"en": "v2", "zh": "offline_structured_v4"},
}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def metric(rows: list[dict]) -> dict:
    by_paper: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        by_paper[row["paper_id"]].append(row["full_minimal_set"])
    return {
        "numerator": sum(row["full_minimal_set"] for row in rows),
        "denominator": len(rows),
        "rate": sum(row["full_minimal_set"] for row in rows) / len(rows) if rows else None,
        "per_paper": {
            paper: {"numerator": sum(values), "denominator": len(values)}
            for paper, values in sorted(by_paper.items())
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    coverage = read(args.coverage)
    run = read(args.run)
    selected = [row for row in coverage["rows"] if row["reference_verdict"] != "insufficient"]
    first_warm = [row for row in run["rows"] if row["repetition"] == 1]
    arms = {}
    for arm, routes in ARMS.items():
        arm_coverage = [row for row in selected if row["policy"] == routes[row["language"]]]
        arm_run = [row for row in first_warm if row["policy"] == routes[row["language"]]]
        arms[arm] = {
            "exact_span_coverage": metric(arm_coverage),
            "by_language": {
                language: metric([row for row in arm_coverage if row["language"] == language])
                for language in ("en", "zh")
            },
            "cost": {
                "requests": len(arm_run),
                "mean_response_bytes": statistics.mean(row["response_bytes"] for row in arm_run),
                "mean_audit_bytes": statistics.mean(row["audit_bytes"] for row in arm_run),
                "p95_query_ms": 1000
                * sorted(row["query_seconds"] for row in arm_run)[
                    max(0, math.ceil(len(arm_run) * 0.95) - 1)
                ],
            },
        }
    payload = {
        "kind": "round4_policy_comparison",
        "warning": (
            "Templated self-review development fixture. Exact-span containment is not semantic "
            "ESR, insufficient-claim safety, independent review, or promotion evidence."
        ),
        "run_complete": run["complete"],
        "run_requests": len(run["rows"]),
        "replay_failures": sum(not row["replay_integrity"] for row in run["rows"]),
        "budget_failures": sum(row.get("budget_ok") is False for row in run["rows"]),
        "arms": arms,
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
