"""Audit a frozen Round 4 fixture before any promotion retrieval run.

This checks fixture scale, per-paper verdict quotas, risk-layer coverage,
bibliography leakage, and declared author/reviewer separation. It cannot prove
that a reviewer is human, independent, or truthfully identified.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

try:  # Direct script execution and package-style test imports use different roots.
    from scripts.round4_eval import read, validate_gold, validate_queries, validate_sources, write
    from scripts.round4_holdout_authoring import bibliography_like
except ModuleNotFoundError:  # pragma: no cover - exercised by CLI smoke checks
    from round4_eval import read, validate_gold, validate_queries, validate_sources, write
    from round4_holdout_authoring import bibliography_like

TARGET = {"supported": 4, "contradicted": 3, "insufficient": 3}


def audit(queries_path: Path, gold_path: Path, input_dir: Path, extractions_path: Path) -> dict:
    queries = read(queries_path)
    gold = read(gold_path)
    validate_queries(queries)
    validate_sources(queries, input_dir)
    cases = validate_gold(queries_path, gold, read(extractions_path))
    checks: dict[str, dict] = {}

    def record(name: str, passed: bool, detail) -> None:
        checks[name] = {"passed": passed, "detail": detail}

    papers = queries["papers"]
    intents = queries["intents"]
    record(
        "scale",
        len(papers) >= 15 and len(intents) >= 150,
        {"papers": len(papers), "intents": len(intents)},
    )
    domains = Counter(paper["domain"] for paper in papers)
    record(
        "domain_diversity",
        len(domains) >= 4 and sum(count >= 2 for count in domains.values()) >= 4,
        dict(sorted(domains.items())),
    )
    by_paper = defaultdict(Counter)
    verdicts = Counter()
    tags = Counter()
    review_failures = []
    reference_like = []
    for intent in intents:
        review = intent["equivalence_review"]
        if review["independence"] != "independent_review":
            review_failures.append(f"{intent['intent_id']}: query not independently reviewed")
    for intent_id, case in cases.items():
        by_paper[case["paper_id"]][case["reference_verdict"]] += 1
        verdicts[case["reference_verdict"]] += 1
        tags.update(case["tags"])
        review = case["review"]
        if review["independence"] != "independent_review":
            review_failures.append(f"{intent_id}: gold not independently reviewed")
        for span in case["spans"]:
            if bibliography_like(span["quote"]):
                reference_like.append({"intent_id": intent_id, "span_id": span["span_id"]})
    quota_failures = {
        paper_id: dict(counts)
        for paper_id, counts in by_paper.items()
        if any(counts[label] != expected for label, expected in TARGET.items())
    }
    record("per_paper_verdict_quota", not quota_failures, quota_failures or TARGET)
    record(
        "verdict_totals",
        verdicts == Counter({k: v * len(papers) for k, v in TARGET.items()}),
        dict(verdicts),
    )
    record(
        "risk_layers",
        tags["table_numeric"] >= 20
        and tags["scope_limitation"] >= 20
        and tags["condition_counterexample"] >= 20,
        dict(tags),
    )
    record("independent_review_records", not review_failures, review_failures[:30])
    record("bibliography_filter", not reference_like, reference_like)
    record(
        "frozen",
        queries["status"] == "frozen" and queries["split"] == "holdout",
        {"status": queries["status"], "split": queries["split"]},
    )
    ready = all(item["passed"] for item in checks.values())
    return {
        "kind": "round4_promotion_fixture_audit",
        "fixture_ready": ready,
        "promotion_eligible": False,
        "promotion_reason": (
            "Fixture checks passed, but this audit cannot verify reviewer identity, independence, custody, or later blind ratings."
            if ready
            else "Fixture checks failed."
        ),
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--extractions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.queries, args.gold, args.input_dir, args.extractions)
    write(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["fixture_ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
