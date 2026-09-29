"""Frozen internal contract for the optional 0.2 semantic verifier.

The contract deliberately separates model observations from the deterministic
policy that produces a public verdict.  Evidence excerpts are untrusted data;
the backend may only cite IDs present in :class:`VerifierRequest`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .models import FabricError, Locator, Model, sha
from .semantic import ConditionDimension, SemanticAssessment, SemanticVerdict, semantic_verdict

VERIFIER_CONTRACT_VERSION: Literal["verifier-contract-v1"] = "verifier-contract-v1"
VERIFIER_POLICY_VERSION: Literal["conservative-three-way-v1"] = "conservative-three-way-v1"


class AtomicClaim(Model):
    """One independently assessable assertion copied from the original claim."""

    atom_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=4000)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    material_conditions: list[ConditionDimension] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def valid_atom(self):
        if self.char_end <= self.char_start:
            raise ValueError("atomic claim has an empty or reversed span")
        if len(set(self.material_conditions)) != len(self.material_conditions):
            raise ValueError("material condition dimensions must be unique")
        return self


class VerifierEvidence(Model):
    """Bounded, grounded excerpt sent to a verifier backend as untrusted data."""

    evidence_id: str = Field(min_length=1, max_length=200)
    edition_id: str = Field(min_length=1, max_length=200)
    document_id: str = Field(min_length=1, max_length=200)
    source_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    excerpt: str = Field(min_length=1, max_length=6000)
    excerpt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    locator: Locator

    @model_validator(mode="after")
    def verify_excerpt_hash(self):
        if sha(self.excerpt.encode()) != self.excerpt_hash:
            raise ValueError("verifier evidence excerpt hash mismatch")
        if len(self.excerpt) != self.locator.char_end - self.locator.char_start:
            raise ValueError("verifier evidence excerpt length does not match its locator")
        return self


class VerifierRequest(Model):
    """Complete model-visible payload for one claim and one paper edition."""

    contract_version: Literal["verifier-contract-v1"] = VERIFIER_CONTRACT_VERSION
    claim_id: str = Field(min_length=1, max_length=200)
    claim_text: str = Field(min_length=1, max_length=10000)
    context: str | None = Field(default=None, max_length=10000)
    edition_id: str = Field(min_length=1, max_length=200)
    atoms: list[AtomicClaim] = Field(min_length=1, max_length=8)
    evidence: list[VerifierEvidence] = Field(min_length=1, max_length=6)
    evidence_char_budget: int = Field(default=6000, ge=1, le=6000)
    policy_version: Literal["conservative-three-way-v1"] = VERIFIER_POLICY_VERSION

    @model_validator(mode="after")
    def validate_payload(self):
        atom_ids = [item.atom_id for item in self.atoms]
        if len(set(atom_ids)) != len(atom_ids):
            raise ValueError("atomic claim IDs must be unique")
        previous_end = -1
        for atom in self.atoms:
            if atom.char_end > len(self.claim_text):
                raise ValueError("atomic claim span exceeds the source claim")
            if self.claim_text[atom.char_start : atom.char_end] != atom.text:
                raise ValueError("atomic claim text must exactly match its source span")
            if atom.char_start < previous_end:
                raise ValueError("atomic claim spans must be ordered and non-overlapping")
            previous_end = atom.char_end

        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("verifier evidence IDs must be unique")
        if any(item.edition_id != self.edition_id for item in self.evidence):
            raise ValueError("all verifier evidence must belong to the selected edition")
        if sum(len(item.excerpt) for item in self.evidence) > self.evidence_char_budget:
            raise ValueError("verifier evidence exceeds the declared character budget")
        return self


class AtomicJudgment(Model):
    atom_id: str = Field(min_length=1, max_length=100)
    assessment: SemanticAssessment


class VerifierResponse(Model):
    """Strict structured model output before deterministic application policy."""

    contract_version: Literal["verifier-contract-v1"] = VERIFIER_CONTRACT_VERSION
    judgments: list[AtomicJudgment] = Field(min_length=1, max_length=8)
    rationale: str = Field(min_length=1, max_length=3000)

    @model_validator(mode="after")
    def unique_atoms(self):
        identifiers = [item.atom_id for item in self.judgments]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("verifier response contains duplicate atomic claim IDs")
        return self


class VerifierUsage(Model):
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_output_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_token_breakdown(self):
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached input tokens cannot exceed input tokens")
        if self.reasoning_output_tokens > self.output_tokens:
            raise ValueError("reasoning output tokens cannot exceed output tokens")
        return self


class VerifierProvenance(Model):
    """Runtime fields that must be copied into the eventual EvidenceReceipt."""

    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    model_revision: str | None = Field(default=None, max_length=200)
    response_id: str | None = Field(default=None, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=100)
    prompt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    output_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_version: Literal["conservative-three-way-v1"] = VERIFIER_POLICY_VERSION
    elapsed_ms: int = Field(ge=0)
    attempts: int = Field(ge=1, le=3)
    fallback_used: bool = False
    pricing_version: str | None = Field(default=None, max_length=100)
    usage: VerifierUsage


def validate_verifier_response(request: VerifierRequest, response: VerifierResponse) -> None:
    """Reject missing atoms, invented evidence IDs and citations over budget."""

    requested = [item.atom_id for item in request.atoms]
    returned = [item.atom_id for item in response.judgments]
    if returned != requested:
        raise FabricError(
            "invalid_model_output",
            "Verifier response must cover every atomic claim once and in input order.",
        )
    candidates = {item.evidence_id: len(item.excerpt) for item in request.evidence}
    for judgment in response.judgments:
        unknown = set(judgment.assessment.cited_evidence_ids) - set(candidates)
        if unknown:
            raise FabricError(
                "invalid_model_output", "Verifier response cites unknown evidence IDs."
            )
        cited_chars = sum(candidates[item] for item in judgment.assessment.cited_evidence_ids)
        if cited_chars > request.evidence_char_budget:
            raise FabricError(
                "invalid_model_output", "Verifier response exceeds the evidence budget."
            )


def aggregate_verifier_verdict(
    request: VerifierRequest, response: VerifierResponse
) -> SemanticVerdict:
    """Derive a conservative claim verdict after validating the model response.

    A direct same-scope contradiction makes a conjunctive claim contradicted.
    Otherwise every atom must be supported; any unresolved atom causes abstention.
    """

    validate_verifier_response(request, response)
    verdicts = [semantic_verdict(item.assessment) for item in response.judgments]
    if "contradicted" in verdicts:
        return "contradicted"
    if all(item == "supported" for item in verdicts):
        return "supported"
    return "insufficient_evidence"
