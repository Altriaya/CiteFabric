import json

import pytest

from scripts.semantic_contract_eval import prepare, score, strict_output_schema, validate


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_semantic_experiment_keeps_gold_out_and_scores_policy(tmp_path):
    input_dir = tmp_path / "input"
    prepared = tmp_path / "prepared"
    outputs = tmp_path / "outputs"
    source = {
        "paper_id": "paper-a",
        "paper_title": "Paper A",
        "intents": [
            {
                "intent_id": "a-01",
                "question_zh": "结果是什么？",
                "retrieval_query_en": "What is the result?",
                "claim_zh": "结果是 5。",
                "evidence_sets": [
                    {
                        "tier": tier,
                        "evidence": [{"candidate_id": "E1", "page": 1, "excerpt": "Result: 5"}],
                    }
                    for tier in ("single", "double", "four")
                ],
            }
        ],
    }
    dump(input_dir / "paper-a.json", source)
    prepare(input_dir, prepared)
    prompt = (prepared / "prompts/paper-a.txt").read_text(encoding="utf-8")
    assert "reference_verdict" not in prompt and "Result: 5" in prompt

    judgment = {
        "tier": "single",
        "coverage": "complete",
        "relation": "supports",
        "absence_basis": "not_applicable",
        "conditions": [
            {
                "dimension": "value",
                "claim_value": "5",
                "status": "matched",
                "evidence_ids": ["E1"],
                "rationale": "The value is stated.",
            }
        ],
        "cited_evidence_ids": ["E1"],
        "rationale": "The evidence directly states the result.",
    }
    output = {
        "contract_version": "semantic-assessment-v2",
        "intents": [
            {
                "intent_id": "a-01",
                "judgments": [dict(judgment, tier=tier) for tier in ("single", "double", "four")],
            }
        ],
    }
    dump(outputs / "paper-a.json", output)
    merged_path = tmp_path / "merged.json"
    validate(input_dir, outputs, merged_path)

    gold = {
        "cases": [{"intent_id": "a-01", "reference_verdict": "supported"}],
    }
    control = {
        "rows": [
            {"intent_id": "a-01", "tier": tier, "selector_complete": True}
            for tier in ("single", "double", "four")
        ]
    }
    dump(tmp_path / "gold.json", gold)
    dump(tmp_path / "control.json", control)
    result = score(
        merged_path, tmp_path / "gold.json", tmp_path / "control.json", tmp_path / "scores.json"
    )
    assert result["tiers"]["four"]["classification"] == {"numerator": 1, "denominator": 1}
    assert result["rows"][-1]["verdict"] == "supported"


def test_model_output_schema_requires_every_property():
    schema = strict_output_schema()

    def inspect(value):
        if isinstance(value, dict):
            if "properties" in value:
                assert set(value["required"]) == set(value["properties"])
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    inspect(schema)


def test_validation_reports_unknown_candidate_ids(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    source = {
        "paper_id": "a",
        "paper_title": "A",
        "intents": [
            {
                "intent_id": "a-01",
                "question_zh": "Q",
                "retrieval_query_en": "Q",
                "claim_zh": "C",
                "evidence_sets": [
                    {"tier": tier, "evidence": [{"candidate_id": "E1", "excerpt": "x"}]}
                    for tier in ("single", "double", "four")
                ],
            }
        ],
    }
    dump(input_dir / "a.json", source)
    judgment = {
        "tier": "single",
        "coverage": "complete",
        "relation": "supports",
        "absence_basis": "not_applicable",
        "conditions": [
            {
                "dimension": "value",
                "claim_value": "C",
                "status": "matched",
                "evidence_ids": ["BAD"],
                "rationale": "Claimed match.",
            }
        ],
        "cited_evidence_ids": ["BAD"],
        "rationale": "Claimed support.",
    }
    dump(
        output_dir / "a.json",
        {
            "contract_version": "semantic-assessment-v2",
            "intents": [
                {
                    "intent_id": "a-01",
                    "judgments": [
                        dict(judgment, tier=tier) for tier in ("single", "double", "four")
                    ],
                }
            ],
        },
    )
    merged = tmp_path / "merged.json"
    with pytest.raises(SystemExit, match="Rejected 3"):
        validate(input_dir, output_dir, merged)
    report = json.loads((tmp_path / "merged-invalid.json").read_text())
    assert {item["error"] for item in report["errors"]} == {"invalid_model_output"}
