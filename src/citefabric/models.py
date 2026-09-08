"""Public contracts. Scores rank candidates; they never measure claim support."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid4())


def sha(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Versioned(Model):
    schema_version: Literal["0.1"] = "0.1"


Source = Literal["crossref", "arxiv", "openalex", "semantic_scholar"]
IdentityStatus = Literal["verified", "unresolved", "conflict", "user_asserted"]
SourceKind = Literal["full_text", "abstract", "user_text"]
LocatorKind = Literal["pdf_text", "plain_text", "abstract"]
CacheStatus = Literal["miss", "fresh", "stale", "not_applicable"]
OutcomeStatus = Literal[
    "ok",
    "no_results",
    "partial",
    "rate_limited",
    "unavailable",
    "permission_denied",
    "parse_failed",
    "unsupported",
    "not_configured",
    "cancelled",
]
ResultStatus = Literal["ok", "partial", "no_results", "failed"]


class Author(Model):
    display_name: str
    given: str | None = None
    family: str | None = None
    orcid: str | None = None
    organization: str | None = None


class Issued(Model):
    year: int | None = Field(default=None, ge=1, le=9999)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)

    @model_validator(mode="after")
    def valid_date(self):
        if self.month is not None and self.year is None:
            raise ValueError("month requires year")
        if self.day is not None:
            if self.month is None or self.year is None:
                raise ValueError("day requires year and month")
            datetime(self.year, self.month, self.day)
        return self


class ExternalID(Model):
    namespace: Literal["doi", "arxiv", "openalex", "s2", "pmid"]
    value: str
    version: str | None = None
    source_record_ids: list[str] = Field(default_factory=list)


class DocumentCandidate(Model):
    url: str
    provider: str
    version: str | None = None
    license: str | None = None
    access_type: Literal["open_access", "unknown"] = "unknown"


class SourceRecord(Versioned):
    record_id: str = Field(default_factory=new_id)
    provider: str
    source_id: str
    title: str = Field(min_length=1, max_length=10000)
    authors: list[Author] = Field(default_factory=list)
    issued: Issued = Field(default_factory=Issued)
    venue: str | None = None
    kind: str = "unknown"
    version: str | None = None
    external_ids: list[ExternalID] = Field(default_factory=list)
    related_ids: list[ExternalID] = Field(default_factory=list)
    abstract: str | None = None
    candidates: list[DocumentCandidate] = Field(default_factory=list)
    open_access: bool | None = None
    publication_status: str = "unknown"
    retrieved_at: str = Field(default_factory=now)
    source_uri: str | None = None


class MetadataSnapshot(Versioned):
    snapshot_id: str = Field(default_factory=new_id)
    edition_id: str
    title: str
    authors: list[Author]
    issued: Issued
    venue: str | None = None
    field_provenance: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    selection_policy_version: str = "source-priority-v1"
    created_at: str = Field(default_factory=now)


class Edition(Versioned):
    edition_id: str = Field(default_factory=new_id)
    fabric_id: str
    kind: str = "unknown"
    version: str | None = None
    external_ids: list[ExternalID] = Field(default_factory=list)
    metadata_snapshot_id: str
    publication_status: dict[str, Any] = Field(default_factory=lambda: {"status": "unknown"})
    identity_status: IdentityStatus = "unresolved"


class Paper(Versioned):
    fabric_id: str = Field(default_factory=lambda: "fabric:" + new_id())
    created_at: str = Field(default_factory=now)
    edition_ids: list[str] = Field(default_factory=list)
    preferred_edition_id: str | None = None
    relations: list[dict[str, Any]] = Field(default_factory=list)
    identity_status: IdentityStatus = "unresolved"


class Coverage(Model):
    source_kind: Literal["full_text", "abstract", "user_text"]
    pages_total: int | None = None
    pages_parsed: int | None = None
    pages_failed: list[int] = Field(default_factory=list)
    sections_searched: list[str] = Field(default_factory=list)
    truncated: bool = False


class Document(Versioned):
    document_id: str = Field(default_factory=new_id)
    edition_id: str
    media_type: str
    byte_length: int = Field(ge=0)
    source_hash: str
    version_label: str | None = None
    binding: dict[str, Any]
    access: dict[str, Any]
    retrieval_event_ids: list[str]
    source_kind: Literal["full_text", "abstract", "user_text"] = "full_text"


class RetrievalEvent(Versioned):
    event_id: str = Field(default_factory=new_id)
    document_id: str
    provider: str
    source_uri: str
    retrieved_at: str = Field(default_factory=now)
    http_status: int | None = None
    etag: str | None = None
    license: str | None = None


class TextUnit(Model):
    text_unit_id: str
    page: int | None = Field(default=None, ge=1)
    text: str


class ExtractionSnapshot(Versioned):
    extraction_id: str = Field(default_factory=new_id)
    document_id: str
    parser: str
    parser_version: str
    config_hash: str
    normalization_version: str = "identity-utf8-v1"
    text_snapshot: str
    text_units: list[TextUnit]
    text_hash: str
    coverage: Coverage
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def verify_text(self):
        if self.text_snapshot != "\f".join(x.text for x in self.text_units):
            raise ValueError("text snapshot does not match units")
        if sha(self.text_snapshot.encode()) != self.text_hash:
            raise ValueError("text hash mismatch")
        if len({u.text_unit_id for u in self.text_units}) != len(self.text_units):
            raise ValueError("duplicate text unit IDs")
        return self


class Locator(Model):
    kind: Literal["pdf_text", "plain_text", "abstract"]
    page: int | None = Field(default=None, ge=1)
    page_label: str | None = None
    section: str | None = None
    text_unit_id: str
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    bbox: tuple[float, float, float, float] | None = None
    table_id: str | None = None
    cell: dict[str, int] | None = None

    @model_validator(mode="after")
    def validate_location(self):
        if self.char_end <= self.char_start:
            raise ValueError("empty or reversed character range")
        if self.kind == "pdf_text" and self.page is None:
            raise ValueError("PDF evidence requires a physical page number")
        return self


class EvidenceObject(Versioned):
    evidence_id: str = Field(default_factory=new_id)
    fabric_id: str
    edition_id: str
    document_id: str
    extraction_id: str
    retrieval_event_id: str
    source_hash: str
    text_hash: str
    locator: Locator
    excerpt: str = Field(min_length=1)
    excerpt_hash: str
    source_kind: Literal["full_text", "abstract", "user_text"]
    grounding: dict[str, Any]
    context_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def verify_excerpt(self):
        if sha(self.excerpt.encode()) != self.excerpt_hash:
            raise ValueError("excerpt hash mismatch")
        if len(self.excerpt) != self.locator.char_end - self.locator.char_start:
            raise ValueError("excerpt length does not match locator")
        return self


class Claim(Versioned):
    claim_id: str = Field(default_factory=new_id)
    text: str
    context: str | None = None
    language: str = "und"
    created_at: str = Field(default_factory=now)


class ClaimAssessment(Versioned):
    assessment_id: str = Field(default_factory=new_id)
    claim_id: str
    edition_id: str
    verdict: Literal[
        "supported", "partially_supported", "contradicted", "insufficient_evidence", "unavailable"
    ]
    reason_code: str
    subclaims: list[dict[str, Any]] = Field(default_factory=list)
    evidence_relations: list[dict[str, str]] = Field(default_factory=list)
    rationale: str
    limitations: list[str]
    coverage: dict[str, Any]
    verifier: dict[str, Any]
    usage: dict[str, Any] = Field(
        default_factory=lambda: dict(
            input_tokens=None, output_tokens=None, cost=None, currency=None
        )
    )
    created_at: str = Field(default_factory=now)


class EvidenceReceipt(Versioned):
    receipt_id: str = Field(default_factory=new_id)
    claim_snapshot: Claim
    metadata_snapshot_ids: list[str]
    assessment: ClaimAssessment
    evidence_ids: list[str]
    document_hashes: dict[str, str]
    identity_assessments: list[dict[str, Any]]
    grounding_status: Literal["verified", "failed", "not_checked"]
    verification_config_hash: str
    created_at: str = Field(default_factory=now)
    supersedes_receipt_id: str | None = None

    @model_validator(mode="after")
    def verify_assessment(self):
        if self.assessment.claim_id != self.claim_snapshot.claim_id:
            raise ValueError("assessment belongs to a different claim")
        ids = {e["evidence_id"] for e in self.assessment.evidence_relations}
        if not ids.issubset(self.evidence_ids):
            raise ValueError("assessment references unknown evidence")
        if self.assessment.verdict in {"supported", "partially_supported", "contradicted"}:
            if not ids or self.grounding_status != "verified":
                raise ValueError("semantic verdict requires grounded evidence")
        return self


class Outcome(Model):
    scope: str = "provider"
    id: str
    status: Literal[
        "ok",
        "no_results",
        "partial",
        "rate_limited",
        "unavailable",
        "permission_denied",
        "parse_failed",
        "unsupported",
        "not_configured",
        "cancelled",
    ]
    code: str | None = None
    retryable: bool = False
    retry_after_seconds: float | None = None
    attempts: int = 0
    elapsed_ms: int = 0
    records_received: int | None = None
    records_valid: int | None = None
    cache_status: Literal["miss", "fresh", "stale", "not_applicable"] = "not_applicable"


class ErrorDetail(Model):
    code: str
    message: str
    scope: str = "request"
    item_id: str | None = None
    retryable: bool = False


class ResultMeta(Model):
    elapsed_ms: int = 0
    cache_status: str = "not_applicable"
    stale: bool = False
    truncated: bool = False
    next_cursor: str | None = None
    coverage: dict[str, Any] = Field(default_factory=dict)


class Result(Versioned):
    request_id: str = Field(default_factory=new_id)
    status: Literal["ok", "partial", "no_results", "failed"] = "ok"
    data: dict[str, Any] | None = None
    outcomes: list[Outcome] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    meta: ResultMeta = Field(default_factory=ResultMeta)


def aggregate(outcomes: list[Outcome], has_data: bool) -> ResultStatus:
    good = sum(o.status in {"ok", "no_results", "partial"} for o in outcomes)
    degraded = any(
        o.status not in {"ok", "no_results"} or o.cache_status == "stale" for o in outcomes
    )
    if degraded:
        return "partial" if good or has_data else "failed"
    return "ok" if has_data else "no_results"


class FabricError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable

    def result(self, item_id: str | None = None) -> Result:
        return Result(
            status="failed",
            errors=[
                ErrorDetail(
                    code=self.code, message=self.message, item_id=item_id, retryable=self.retryable
                )
            ],
        )


class Filters(Model):
    year_from: int | None = Field(default=None, ge=1, le=9999)
    year_to: int | None = Field(default=None, ge=1, le=9999)
    open_access: bool | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from must not exceed year_to")
        return self


class SearchRequest(Model):
    query: str = Field(min_length=1, max_length=2000)
    filters: Filters = Field(default_factory=Filters)
    limit: int = Field(default=10, ge=1, le=20)
    sources: list[Source] | None = Field(default=None, min_length=1, max_length=4)
    sort: Literal["relevance", "recent"] = "relevance"
    evidence_ready: bool = False
    cursor: str | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.query.strip():
            raise ValueError("query must not be blank")
        if self.sources and len(set(self.sources)) != len(self.sources):
            raise ValueError("sources must be unique")
        return self


class PaperSelector(Model):
    ref: str = Field(min_length=1, max_length=2048)
    edition_id: str | None = None


class GetRequest(PaperSelector):
    refresh: bool = False


class EvidenceRequest(Model):
    papers: list[PaperSelector] = Field(min_length=1, max_length=3)
    query: str = Field(min_length=1, max_length=2000)
    max_passages: int = Field(default=6, ge=1, le=12)
    max_chars: int = Field(default=6000, ge=500, le=16000)
    allow_abstract: bool = False
    expand_query: bool = True
    include_context: bool = True
    retrieval_policy: Literal["v2", "structured_v3"] = "v2"


class VerifyRequest(Model):
    claim: str = Field(min_length=1, max_length=4000)
    papers: list[PaperSelector] = Field(min_length=1, max_length=3)
    evidence_ids: list[str] | None = Field(default=None, min_length=1, max_length=12)
    context: str | None = Field(default=None, max_length=4000)


class ExportRequest(Model):
    papers: list[PaperSelector] = Field(min_length=1, max_length=50)
    format: Literal["bibtex", "csl_json", "apa", "ieee"] = "bibtex"
    receipt_ids: list[str] | None = Field(default=None, max_length=100)
