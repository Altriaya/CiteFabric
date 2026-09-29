from scripts.verifier_promotion_gate import PromotionEvaluation, score


def evaluation(*, introduce_failure=False):
    papers = []
    cases = []
    labels = ("supported", "contradicted", "insufficient_evidence")
    risk_tags = (
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
    )
    for paper_number in range(12):
        paper_id = f"P{paper_number:02d}"
        papers.append(
            {
                "paper_id": paper_id,
                "domain": f"domain-{paper_number % 4}",
                "document_language": "zh" if paper_number % 2 else "en",
                "source_hash": "sha256:" + f"{paper_number + 1:064x}",
                "extraction_hash": "sha256:" + f"{paper_number + 20:064x}",
            }
        )
        for offset in range(9):
            verdict = labels[(paper_number * 9 + offset) % 3]
            cases.append(
                {
                    "case_id": f"{paper_id}-{offset}",
                    "paper_id": paper_id,
                    "claim_language": "zh" if offset % 2 else "en",
                    "risk_tags": [risk_tags[(paper_number * 9 + offset) % len(risk_tags)]],
                    "reference_verdict": verdict,
                    "predicted_verdict": verdict,
                    "citations_valid": True,
                    "grounding_verified": True,
                    "receipt_present": True,
                    "receipt_replayed": True,
                    "latency_ms": 1000,
                    "cost_usd": 0.01,
                }
            )
    if introduce_failure:
        target = next(
            case
            for case in cases
            if case["reference_verdict"] == "contradicted" and "numeric" in case["risk_tags"]
        )
        target["predicted_verdict"] = "supported"
    return PromotionEvaluation.model_validate(
        {
            "benchmark_id": "sealed-holdout-1",
            "sealed_before_run": True,
            "independence_verified": True,
            "double_annotated": True,
            "adjudicated": True,
            "retrieval_frozen": True,
            "verifier_code_frozen": True,
            "model_frozen": True,
            "prompt_frozen": True,
            "thresholds": {"false_support_rate_max": 1.0} if introduce_failure else {},
            "papers": papers,
            "cases": cases,
        }
    )


def test_promotion_gate_passes_complete_high_quality_holdout():
    report = score(evaluation())
    assert report["decision"] == "pass"
    assert report["metrics"]["macro_f1"] == 1
    assert report["failures"] == []


def test_promotion_gate_fails_any_critical_false_support():
    report = score(evaluation(introduce_failure=True))
    assert report["decision"] == "fail"
    assert "performance.critical_false_supports" in report["failures"]
