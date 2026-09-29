import pytest
from pydantic import ValidationError

from citefabric.models import FabricError, sha
from citefabric.verifier_contract import (
    VerifierRequest,
    VerifierResponse,
    aggregate_verifier_verdict,
    validate_verifier_response,
)


def request(**updates):
    claim = "BERT scores 93.2 on SQuAD and is faster."
    value = {
        "claim_id": "C1",
        "claim_text": claim,
        "edition_id": "ED1",
        "atoms": [
            {
                "atom_id": "A1",
                "text": "BERT scores 93.2 on SQuAD",
                "char_start": 0,
                "char_end": 25,
                "material_conditions": ["model", "value", "dataset"],
            },
            {
                "atom_id": "A2",
                "text": "is faster",
                "char_start": 30,
                "char_end": 39,
                "material_conditions": ["direction", "baseline"],
            },
        ],
        "evidence": [
            {
                "evidence_id": "E1",
                "edition_id": "ED1",
                "document_id": "D1",
                "source_hash": "sha256:" + "1" * 64,
                "excerpt": "BERT reports 93.2 on the SQuAD test set.",
                "excerpt_hash": sha(b"BERT reports 93.2 on the SQuAD test set."),
                "locator": {
                    "kind": "pdf_text",
                    "page": 7,
                    "text_unit_id": "P7",
                    "char_start": 0,
                    "char_end": 40,
                },
            }
        ],
    }
    value.update(updates)
    return VerifierRequest.model_validate(value)


def assessment(relation="supports"):
    status = "matched" if relation == "supports" else "contradicted_same_scope"
    return {
        "coverage": "complete",
        "relation": relation,
        "absence_basis": "not_applicable",
        "conditions": [
            {
                "dimension": "value",
                "claim_value": "93.2",
                "status": status,
                "evidence_ids": ["E1"],
                "rationale": "The excerpt directly reports the value.",
            }
        ],
        "cited_evidence_ids": ["E1"],
        "rationale": "Direct same-edition evidence.",
    }


def response(second=None):
    return VerifierResponse.model_validate(
        {
            "judgments": [
                {"atom_id": "A1", "assessment": assessment()},
                {"atom_id": "A2", "assessment": second or assessment()},
            ],
            "rationale": "Every atom was assessed independently.",
        }
    )


def test_verifier_contract_accepts_grounded_atoms_and_derives_three_way_verdict():
    item = request()
    assert aggregate_verifier_verdict(item, response()) == "supported"
    assert (
        aggregate_verifier_verdict(item, response(assessment("contradicts_same_scope")))
        == "contradicted"
    )
    unresolved = {
        "coverage": "partial",
        "relation": "not_established",
        "absence_basis": "unknown_from_excerpts",
        "conditions": [
            {
                "dimension": "model",
                "claim_value": "BERT",
                "status": "matched",
                "evidence_ids": ["E1"],
                "rationale": "The model is named.",
            },
            {
                "dimension": "baseline",
                "claim_value": "comparison baseline",
                "status": "missing",
                "evidence_ids": [],
                "rationale": "No comparison baseline is supplied.",
            },
        ],
        "cited_evidence_ids": ["E1"],
        "rationale": "A material comparison condition is missing.",
    }
    assert aggregate_verifier_verdict(item, response(unresolved)) == "insufficient_evidence"


def test_verifier_contract_rejects_changed_span_and_cross_edition_evidence():
    with pytest.raises(ValidationError, match="exactly match"):
        request(
            atoms=[
                {
                    "atom_id": "A1",
                    "text": "BERT scores 94.2 on SQuAD",
                    "char_start": 0,
                    "char_end": 25,
                    "material_conditions": ["model", "value", "dataset"],
                }
            ]
        )
    changed = request().model_dump(mode="json")
    changed["evidence"][0]["edition_id"] = "ED2"
    with pytest.raises(ValidationError, match="selected edition"):
        VerifierRequest.model_validate(changed)


def test_verifier_contract_rejects_missing_atoms_and_invented_evidence():
    item = request()
    missing = response().model_copy(update={"judgments": response().judgments[:1]})
    with pytest.raises(FabricError, match="every atomic claim"):
        validate_verifier_response(item, missing)

    raw = response().model_dump(mode="json")
    raw["judgments"][0]["assessment"]["conditions"][0]["evidence_ids"] = ["E9"]
    raw["judgments"][0]["assessment"]["cited_evidence_ids"] = ["E9"]
    invented = VerifierResponse.model_validate(raw)
    with pytest.raises(FabricError, match="unknown evidence"):
        validate_verifier_response(item, invented)
