"""Score a sealed 0.2 verifier holdout and apply the frozen promotion gate."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from citefabric.models import Model

Verdict = Literal["supported", "contradicted", "insufficient_evidence"]
PredictedVerdict = Literal["supported", "contradicted", "insufficient_evidence", "unavailable"]
Language = Literal["zh", "en", "multilingual", "other"]
RiskTag = Literal[
    "numeric",
    "unit",
    "dataset",
    "model",
    "population",
    "scope",
    "time",
    "comparison",
    "negation",
    "table",
    "cross_language",
    "compound_claim",
    "absence",
]
REQUIRED_RISK_TAGS = {
    "numeric",
    "unit",
    "dataset",
    "model",
    "population",
    "scope",
    "time",
    "comparison",
    "negation",
    "table",
    "cross_language",
    "compound_claim",
    "absence",
}
LABELS: tuple[Verdict, ...] = ("supported", "contradicted", "insufficient_evidence")
CRITICAL_TAGS = {
    "numeric",
    "unit",
    "dataset",
    "model",
    "population",
    "scope",
    "time",
    "comparison",
    "negation",
}


class GateThresholds(Model):
    minimum_papers: int = Field(default=12, ge=1)
    minimum_cases: int = Field(default=100, ge=1)
    minimum_cases_per_label: int = Field(default=20, ge=1)
    minimum_cases_per_paper: int = Field(default=5, ge=1)
    minimum_domains: int = Field(default=4, ge=1)
    macro_f1_min: float = Field(default=0.85, ge=0, le=1)
    false_support_rate_max: float = Field(default=0.02, ge=0, le=1)
    insufficient_recall_min: float = Field(default=0.90, ge=0, le=1)
    minimum_paper_accuracy: float = Field(default=0.70, ge=0, le=1)
    unavailable_rate_max: float = Field(default=0.02, ge=0, le=1)
    p95_latency_ms_max: int = Field(default=30000, ge=1)
    mean_cost_usd_max: float | None = Field(default=None, ge=0)


class EvaluationPaper(Model):
    paper_id: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=1, max_length=200)
    document_language: Language
    source_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    extraction_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    development_overlap: bool = False


class EvaluationCase(Model):
    case_id: str = Field(min_length=1, max_length=200)
    paper_id: str = Field(min_length=1, max_length=200)
    claim_language: Language
    risk_tags: list[RiskTag] = Field(min_length=1)
    reference_verdict: Verdict
    predicted_verdict: PredictedVerdict
    citations_valid: bool
    grounding_verified: bool
    receipt_present: bool
    receipt_replayed: bool
    latency_ms: int = Field(ge=0)
    cost_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def unique_risks(self):
        if len(set(self.risk_tags)) != len(self.risk_tags):
            raise ValueError("risk tags must be unique")
        return self


class PromotionEvaluation(Model):
    protocol_version: Literal["verifier-promotion-v1"] = "verifier-promotion-v1"
    benchmark_id: str = Field(min_length=1, max_length=200)
    sealed_before_run: bool
    independence_verified: bool
    double_annotated: bool
    adjudicated: bool
    retrieval_frozen: bool
    verifier_code_frozen: bool
    model_frozen: bool
    prompt_frozen: bool
    thresholds: GateThresholds = Field(default_factory=GateThresholds)
    papers: list[EvaluationPaper]
    cases: list[EvaluationCase]

    @model_validator(mode="after")
    def validate_relations(self):
        paper_ids = [paper.paper_id for paper in self.papers]
        case_ids = [case.case_id for case in self.cases]
        if len(set(paper_ids)) != len(paper_ids):
            raise ValueError("paper IDs must be unique")
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("case IDs must be unique")
        unknown = {case.paper_id for case in self.cases} - set(paper_ids)
        if unknown:
            raise ValueError("every case must reference a declared paper")
        return self


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def percentile95(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)] if ordered else 0


def score(evaluation: PromotionEvaluation) -> dict:
    cases = evaluation.cases
    counts = Counter(case.reference_verdict for case in cases)
    predicted_counts = Counter(case.predicted_verdict for case in cases)
    per_label = {}
    f1s = []
    for label in LABELS:
        true_positive = sum(
            case.reference_verdict == label and case.predicted_verdict == label for case in cases
        )
        false_positive = sum(
            case.reference_verdict != label and case.predicted_verdict == label for case in cases
        )
        false_negative = sum(
            case.reference_verdict == label and case.predicted_verdict != label for case in cases
        )
        precision = ratio(true_positive, true_positive + false_positive)
        recall = ratio(true_positive, true_positive + false_negative)
        f1 = ratio(2 * precision * recall, precision + recall)
        f1s.append(f1)
        per_label[label] = {
            "support": counts[label],
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    false_supports = [
        case
        for case in cases
        if case.predicted_verdict == "supported" and case.reference_verdict != "supported"
    ]
    critical_false_supports = [
        case for case in false_supports if set(case.risk_tags) & CRITICAL_TAGS
    ]
    paper_rows: dict[str, list[EvaluationCase]] = defaultdict(list)
    for case in cases:
        paper_rows[case.paper_id].append(case)
    paper_accuracy = {
        paper_id: ratio(
            sum(case.predicted_verdict == case.reference_verdict for case in rows), len(rows)
        )
        for paper_id, rows in sorted(paper_rows.items())
    }
    costs = [case.cost_usd for case in cases if case.cost_usd is not None]
    metrics = {
        "paper_count": len(evaluation.papers),
        "case_count": len(cases),
        "cases_per_label": dict(counts),
        "cases_per_paper": {key: len(value) for key, value in sorted(paper_rows.items())},
        "domain_count": len({paper.domain for paper in evaluation.papers}),
        "document_languages": sorted({paper.document_language for paper in evaluation.papers}),
        "claim_languages": sorted({case.claim_language for case in cases}),
        "risk_tags": sorted({tag for case in cases for tag in case.risk_tags}),
        "macro_f1": sum(f1s) / len(f1s),
        "per_label": per_label,
        "false_support_rate": ratio(len(false_supports), predicted_counts["supported"]),
        "false_support_count": len(false_supports),
        "critical_false_support_count": len(critical_false_supports),
        "insufficient_recall": per_label["insufficient_evidence"]["recall"],
        "minimum_paper_accuracy": min(paper_accuracy.values(), default=0.0),
        "paper_accuracy": paper_accuracy,
        "unavailable_rate": ratio(predicted_counts["unavailable"], len(cases)),
        "citation_valid_rate": ratio(sum(case.citations_valid for case in cases), len(cases)),
        "grounding_verified_rate": ratio(
            sum(case.grounding_verified for case in cases), len(cases)
        ),
        "receipt_present_rate": ratio(sum(case.receipt_present for case in cases), len(cases)),
        "receipt_replay_rate": ratio(sum(case.receipt_replayed for case in cases), len(cases)),
        "p95_latency_ms": percentile95([case.latency_ms for case in cases]),
        "cost_reporting_rate": ratio(len(costs), len(cases)),
        "mean_cost_usd": sum(costs) / len(costs) if costs else None,
    }
    threshold = evaluation.thresholds
    corpus_checks = {
        "sealed_before_run": evaluation.sealed_before_run,
        "independence_verified": evaluation.independence_verified,
        "double_annotated": evaluation.double_annotated,
        "adjudicated": evaluation.adjudicated,
        "retrieval_frozen": evaluation.retrieval_frozen,
        "verifier_code_frozen": evaluation.verifier_code_frozen,
        "model_frozen": evaluation.model_frozen,
        "prompt_frozen": evaluation.prompt_frozen,
        "minimum_papers": metrics["paper_count"] >= threshold.minimum_papers,
        "minimum_cases": metrics["case_count"] >= threshold.minimum_cases,
        "minimum_cases_per_label": all(
            counts[label] >= threshold.minimum_cases_per_label for label in LABELS
        ),
        "minimum_cases_per_paper": bool(paper_rows)
        and all(len(rows) >= threshold.minimum_cases_per_paper for rows in paper_rows.values()),
        "minimum_domains": metrics["domain_count"] >= threshold.minimum_domains,
        "document_language_coverage": {"zh", "en"}.issubset(metrics["document_languages"]),
        "claim_language_coverage": {"zh", "en"}.issubset(metrics["claim_languages"]),
        "risk_category_coverage": REQUIRED_RISK_TAGS.issubset(metrics["risk_tags"]),
        "no_development_overlap": not any(paper.development_overlap for paper in evaluation.papers),
    }
    performance_checks = {
        "macro_f1": metrics["macro_f1"] >= threshold.macro_f1_min,
        "false_support_rate": metrics["false_support_rate"] <= threshold.false_support_rate_max,
        "critical_false_supports": metrics["critical_false_support_count"] == 0,
        "insufficient_recall": metrics["insufficient_recall"] >= threshold.insufficient_recall_min,
        "minimum_paper_accuracy": metrics["minimum_paper_accuracy"]
        >= threshold.minimum_paper_accuracy,
        "unavailable_rate": metrics["unavailable_rate"] <= threshold.unavailable_rate_max,
        "citations_valid": metrics["citation_valid_rate"] == 1.0,
        "grounding_verified": metrics["grounding_verified_rate"] == 1.0,
        "receipts_present": metrics["receipt_present_rate"] == 1.0,
        "receipts_replayed": metrics["receipt_replay_rate"] == 1.0,
        "latency": metrics["p95_latency_ms"] <= threshold.p95_latency_ms_max,
        "cost_reported": metrics["cost_reporting_rate"] == 1.0,
        "cost_budget": threshold.mean_cost_usd_max is None
        or (
            metrics["mean_cost_usd"] is not None
            and metrics["mean_cost_usd"] <= threshold.mean_cost_usd_max
        ),
    }
    failures = [f"corpus.{name}" for name, passed in corpus_checks.items() if not passed] + [
        f"performance.{name}" for name, passed in performance_checks.items() if not passed
    ]
    return {
        "kind": "verifier-promotion-v1-report",
        "benchmark_id": evaluation.benchmark_id,
        "decision": "pass" if not failures else "fail",
        "failures": failures,
        "thresholds": threshold.model_dump(mode="json"),
        "corpus_checks": corpus_checks,
        "performance_checks": performance_checks,
        "metrics": metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    schema_parser = commands.add_parser("schema")
    schema_parser.add_argument("--output", type=Path, required=True)
    score_parser = commands.add_parser("score")
    score_parser.add_argument("--input", type=Path, required=True)
    score_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "schema":
        value = PromotionEvaluation.model_json_schema()
    else:
        value = score(
            PromotionEvaluation.model_validate_json(args.input.read_text(encoding="utf-8"))
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
