import pytest
from pydantic import ValidationError

from citefabric.models import FabricError
from citefabric.semantic import SemanticAssessment, semantic_verdict, validate_evidence_budget


def assessment(**updates):
    value = {
        "coverage": "complete",
        "relation": "supports",
        "absence_basis": "not_applicable",
        "conditions": [
            {
                "dimension": "dataset",
                "claim_value": "CIFAR-10",
                "status": "matched",
                "evidence_ids": ["E1"],
                "rationale": "The excerpt names CIFAR-10.",
            }
        ],
        "cited_evidence_ids": ["E1"],
        "rationale": "Every material condition is directly supported.",
    }
    value.update(updates)
    return SemanticAssessment.model_validate(value)


def test_conservative_policy_derives_supported_and_same_scope_contradiction():
    assert semantic_verdict(assessment()) == "supported"
    contradicted = assessment(
        relation="contradicts_same_scope",
        conditions=[
            {
                "dimension": "value",
                "claim_value": "90%",
                "status": "contradicted_same_scope",
                "evidence_ids": ["E1"],
                "rationale": "The same experiment reports 80% instead.",
            }
        ],
    )
    assert semantic_verdict(contradicted) == "contradicted"


def test_missing_condition_forces_not_established_and_insufficient():
    value = assessment(
        coverage="partial",
        relation="not_established",
        absence_basis="unknown_from_excerpts",
        conditions=[
            {
                "dimension": "model",
                "claim_value": "Adam CNN",
                "status": "matched",
                "evidence_ids": ["E1"],
                "rationale": "Adam CNN is discussed.",
            },
            {
                "dimension": "dataset",
                "claim_value": "CIFAR-100",
                "status": "missing",
                "evidence_ids": [],
                "rationale": "The excerpts only identify CIFAR-10.",
            },
        ],
    )
    assert semantic_verdict(value) == "insufficient_evidence"


@pytest.mark.parametrize(
    "updates",
    [
        {"coverage": "partial"},
        {
            "relation": "contradicts_same_scope",
            "conditions": [
                {
                    "dimension": "value",
                    "claim_value": "5%",
                    "status": "contradicted_same_scope",
                    "evidence_ids": ["E1"],
                    "rationale": "The excerpt says strong frequency evidence is unavailable.",
                }
            ],
            "absence_basis": "explicit_lack_of_evidence",
        },
        {"relation": "not_established"},
        {"absence_basis": "explicit_lack_of_evidence"},
    ],
)
def test_inconsistent_semantic_observations_are_rejected(updates):
    with pytest.raises(ValidationError):
        assessment(**updates)


def test_application_validator_rejects_unknown_ids_and_character_budget():
    value = assessment()
    validate_evidence_budget(value, {"E1": 100})
    with pytest.raises(FabricError, match="unknown"):
        validate_evidence_budget(value, {"E2": 100})
    with pytest.raises(FabricError, match="budget"):
        validate_evidence_budget(value, {"E1": 6001})
