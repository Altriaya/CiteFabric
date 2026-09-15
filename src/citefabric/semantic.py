"""Strict semantic-assessment observations and conservative verdict policy.

This module defines the contract for a future optional verifier backend.  It does
not call a model and does not change the 0.1 ``verify_claim`` abstention behavior.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import Field, model_validator

from .models import FabricError, Model

EvidenceCoverage = Literal["complete", "partial", "none"]
LogicalRelation = Literal["supports", "contradicts_same_scope", "not_established"]
AbsenceBasis = Literal[
    "not_applicable",
    "explicit_exhaustive_absence",
    "explicit_lack_of_evidence",
    "unknown_from_excerpts",
]
ConditionDimension = Literal[
    "subject",
    "dataset",
    "population",
    "model",
    "method",
    "version",
    "metric",
    "value",
    "unit",
    "direction",
    "baseline",
    "time",
    "scope",
    "causality",
    "other",
]
ConditionStatus = Literal["matched", "contradicted_same_scope", "missing", "ambiguous"]
SemanticVerdict = Literal["supported", "contradicted", "insufficient_evidence"]


class ConditionAssessment(Model):
    """Evidence coverage for one material condition in a claim."""

    dimension: ConditionDimension
    claim_value: str = Field(min_length=1, max_length=1000)
    status: ConditionStatus
    evidence_ids: list[str] = Field(default_factory=list, max_length=6)
    rationale: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_evidence(self):
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("condition evidence IDs must be unique")
        if self.status in {"matched", "contradicted_same_scope"} and not self.evidence_ids:
            raise ValueError("matched or contradicted conditions require evidence")
        return self


class SemanticAssessment(Model):
    """Gold-blind semantic observations consumed by a deterministic policy.

    ``coverage`` asks whether every material claim condition is present in the
    supplied excerpts. ``relation`` distinguishes a true same-scope conflict from
    evidence that merely fails to establish the claim. ``absence_basis`` records
    whether an absence statement is exhaustive, explicitly uncertain, or unknown.
    """

    contract_version: Literal["semantic-assessment-v2"] = "semantic-assessment-v2"
    coverage: EvidenceCoverage
    relation: LogicalRelation
    absence_basis: AbsenceBasis
    conditions: list[ConditionAssessment] = Field(min_length=1, max_length=16)
    cited_evidence_ids: list[str] = Field(default_factory=list, max_length=6)
    rationale: str = Field(min_length=1, max_length=3000)

    @model_validator(mode="after")
    def validate_policy_inputs(self):
        if len(set(self.cited_evidence_ids)) != len(self.cited_evidence_ids):
            raise ValueError("cited evidence IDs must be unique")
        condition_ids = {identifier for item in self.conditions for identifier in item.evidence_ids}
        if not condition_ids.issubset(self.cited_evidence_ids):
            raise ValueError("condition evidence must be included in cited_evidence_ids")

        statuses = [item.status for item in self.conditions]
        unresolved = {"missing", "ambiguous"}
        direct = {"matched", "contradicted_same_scope"}
        if self.coverage == "complete" and any(status in unresolved for status in statuses):
            raise ValueError("complete coverage cannot contain missing or ambiguous conditions")
        if self.coverage == "partial" and not (
            any(status in direct for status in statuses)
            and any(status in unresolved for status in statuses)
        ):
            raise ValueError("partial coverage requires both direct and unresolved conditions")
        if self.coverage == "none" and any(status in direct for status in statuses):
            raise ValueError("no coverage cannot contain matched or contradicted conditions")

        if self.relation == "supports":
            if self.coverage != "complete" or any(status != "matched" for status in statuses):
                raise ValueError("support requires complete coverage with all conditions matched")
            if self.absence_basis != "not_applicable":
                raise ValueError("support cannot rely on an absence basis")
            if not self.cited_evidence_ids:
                raise ValueError("support requires cited evidence")
        elif self.relation == "contradicts_same_scope":
            if self.coverage != "complete":
                raise ValueError("same-scope contradiction requires complete coverage")
            if "contradicted_same_scope" not in statuses:
                raise ValueError("same-scope contradiction requires a conflicting condition")
            if self.absence_basis in {
                "explicit_lack_of_evidence",
                "unknown_from_excerpts",
            }:
                raise ValueError("lack of evidence cannot establish a contradiction")
            if not self.cited_evidence_ids:
                raise ValueError("contradiction requires cited evidence")
        elif self.coverage == "complete":
            raise ValueError("not_established must identify an unresolved material condition")
        return self


def semantic_verdict(assessment: SemanticAssessment) -> SemanticVerdict:
    """Map validated observations to the conservative public three-way verdict."""

    if assessment.relation == "supports" and assessment.coverage == "complete":
        return "supported"
    if assessment.relation == "contradicts_same_scope" and assessment.coverage == "complete":
        return "contradicted"
    return "insufficient_evidence"


def validate_evidence_budget(
    assessment: SemanticAssessment,
    candidates: Mapping[str, int],
    *,
    max_evidence: int = 6,
    max_chars: int = 6000,
) -> None:
    """Reject invented IDs and over-budget citations after model generation."""

    unknown = set(assessment.cited_evidence_ids) - set(candidates)
    if unknown:
        raise FabricError("invalid_model_output", "Semantic assessment cites unknown evidence IDs.")
    if len(assessment.cited_evidence_ids) > max_evidence:
        raise FabricError("invalid_model_output", "Semantic assessment exceeds evidence count.")
    total = sum(candidates[identifier] for identifier in assessment.cited_evidence_ids)
    if total > max_chars:
        raise FabricError("invalid_model_output", "Semantic assessment exceeds evidence budget.")
