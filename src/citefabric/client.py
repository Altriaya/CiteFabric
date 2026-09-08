"""Shared application services for Python, CLI and MCP."""

from __future__ import annotations

import asyncio
import functools
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from . import citations
from .config import Config
from .documents import download, evidence_from_passage, ingest_document
from .evidence_selection import bundles_for
from .evidence_selection import retrieve as structured_retrieve
from .identity import parse_ref
from .models import (
    Claim,
    ClaimAssessment,
    DocumentCandidate,
    Edition,
    ErrorDetail,
    EvidenceReceipt,
    EvidenceRequest,
    ExportRequest,
    FabricError,
    GetRequest,
    Outcome,
    PaperSelector,
    Result,
    SearchRequest,
    SourceRecord,
    VerifyRequest,
    aggregate,
    new_id,
    now,
    sha,
)
from .providers import DiscoveryProvider
from .retrieval import concept_coverage, quality_flags, query_plan, with_context
from .runtime import ProviderRuntime
from .storage import Store, dump


def operation(fn):
    @functools.wraps(fn)
    async def wrapped(self, *args, **kwargs):
        started = time.monotonic()
        try:
            result = await fn(self, *args, **kwargs)
        except FabricError as exc:
            result = exc.result()
        except ValidationError as exc:
            # Do not include input values, which can contain claims or secrets.
            fields = ", ".join(
                ".".join(str(p) for p in e["loc"]) or "request" for e in exc.errors()
            )
            result = FabricError("invalid_argument", "Invalid arguments: " + fields).result()
        result.meta.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    return wrapped


def outcome_error(outcome: Outcome) -> ErrorDetail:
    return ErrorDetail(
        code=outcome.code or outcome.status,
        message=(outcome.code or outcome.status).replace("_", " ") + ".",
        scope=outcome.scope,
        item_id=outcome.id,
        retryable=outcome.retryable,
    )


def result_with(data: dict, outcomes: list[Outcome], has_data: bool, **kwargs) -> Result:
    result = Result(
        status=aggregate(outcomes, has_data),
        data=data,
        outcomes=outcomes,
        errors=[outcome_error(o) for o in outcomes if o.status not in {"ok", "no_results"}],
        **kwargs,
    )
    result.meta.stale = any(o.cache_status == "stale" for o in outcomes)
    return result


class CiteFabricClient:
    """One local workspace. Use as an async context manager to close resources."""

    def __init__(
        self, config: Config | None = None, *, http_client: httpx.AsyncClient | None = None
    ):
        self.config = config or Config.load()
        self.store = Store(self.config.data_dir, self.config.cache_bytes)
        self.runtime = ProviderRuntime(self.config, self.store, http_client)
        self.providers = {
            name: DiscoveryProvider(name, self.runtime)
            for name in ("crossref", "arxiv", "openalex", "semantic_scholar")
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def close(self):
        await self.runtime.close()
        self.store.close()

    def _detail(self, edition: Edition) -> dict:
        return dict(
            edition=edition.model_dump(mode="json"),
            metadata=self.store.metadata(edition.metadata_snapshot_id).model_dump(mode="json"),
            source_records=[
                record.model_dump(mode="json") for record in self.store.records(edition.edition_id)
            ],
            documents=[
                doc.model_dump(mode="json") for doc in self.store.documents(edition.edition_id)
            ],
        )

    async def _request(self, name, *, timeout=None, **kwargs):
        try:
            async with asyncio.timeout(timeout or self.config.search_timeout):
                return await self.providers[name].request(**kwargs)
        except TimeoutError:
            return [], Outcome(
                id=name, status="unavailable", code="provider_timeout", retryable=True
            )
        except FabricError as exc:
            return [], Outcome(
                id=name, status="unavailable", code=exc.code, retryable=exc.retryable
            )

    @operation
    async def search_papers(self, query: str, **kwargs) -> Result:
        request = SearchRequest(query=query, **kwargs)
        selected = request.sources or self.config.sources
        if not selected:
            raise FabricError("invalid_argument", "Select at least one source.")
        plan = request.model_dump(exclude={"limit", "cursor"})
        plan["sources"] = selected
        plan_hash = sha(dump(plan).encode())
        if request.cursor:
            cached = self.store.cache_get("cursor:" + request.cursor)
            if not cached:
                raise FabricError(
                    "cursor_expired", "The local search snapshot has expired; repeat the search."
                )
            snapshot = cached[0]
            if snapshot["plan_hash"] != plan_hash:
                raise FabricError(
                    "invalid_argument", "Cursor parameters differ from the original search."
                )
            return self._search_page(snapshot, request.limit)

        responses = await asyncio.gather(*(self._request(name, query=query) for name in selected))
        outcomes: list[Outcome] = []
        ranked: dict[str, dict[str, Any]] = {}
        received = 0
        valid = 0
        for name, (records, outcome) in zip(selected, responses, strict=True):
            outcomes.append(outcome)
            received += outcome.records_received or 0
            source_best = set()
            for rank, record in enumerate(records, 1):
                edition = self.store.ingest(record)
                valid += 1
                paper_id = edition.fabric_id
                if paper_id not in ranked:
                    ranked[paper_id] = dict(edition=edition, score=0.0, sources=[], editions=set())
                item = ranked[paper_id]
                item["editions"].add(edition.edition_id)
                if paper_id not in source_best:
                    item["score"] += 1 / (60 + rank)
                    item["sources"].append(name)
                    source_best.add(paper_id)
        summaries: list[dict[str, Any]] = []
        for fabric_id, item in ranked.items():
            paper = self.store.paper(fabric_id)
            # Apply filters to the edition actually displayed. Never advertise a
            # v1 result as evidence-ready merely because v2 has a parsed file.
            eligible = []
            order = [item["edition"].edition_id, *paper.edition_ids]
            for eid in dict.fromkeys(order):
                edition = self.store.edition(eid)
                metadata = self.store.metadata(edition.metadata_snapshot_id)
                records = self.store.records(eid)
                documents = self.store.documents(eid)
                ready = any(
                    d.binding["status"] == "verified"
                    and self.store.blob_path(d.source_hash).is_file()
                    for d in documents
                )
                oa_values = [r.open_access for r in records if r.open_access is not None]
                oa = True if True in oa_values else False if oa_values else None
                year = metadata.issued.year
                if request.filters.year_from is not None and (
                    year is None or year < request.filters.year_from
                ):
                    continue
                if request.filters.year_to is not None and (
                    year is None or year > request.filters.year_to
                ):
                    continue
                if (
                    request.filters.open_access is not None
                    and oa is not request.filters.open_access
                ):
                    continue
                if request.evidence_ready and not ready:
                    continue
                eligible.append((edition, metadata, records, ready))
            if not eligible:
                continue
            if request.sort == "recent":
                eligible.sort(key=lambda value: value[1].issued.year or 0, reverse=True)
            edition, metadata, records, ready = eligible[0]
            year = metadata.issued.year
            summaries.append(
                dict(
                    fabric_id=fabric_id,
                    edition_id=edition.edition_id,
                    title=metadata.title,
                    authors=[a.display_name for a in metadata.authors[:5]],
                    authors_truncated=len(metadata.authors) > 5,
                    year=year,
                    external_ids=[e.model_dump(mode="json") for e in edition.external_ids],
                    identity_status=edition.identity_status,
                    sources=item["sources"],
                    available_versions=len(paper.edition_ids),
                    document_availability="cached_parsed"
                    if ready
                    else "candidate"
                    if any(r.candidates for r in records)
                    else "unknown",
                    ranking_score=item["score"],
                    ranking_method="rrf-k60-v1",
                )
            )
        summaries.sort(
            key=lambda x: (
                (-(x["year"] or 0), -x["ranking_score"], x["fabric_id"])
                if request.sort == "recent"
                else (-x["ranking_score"], x["fabric_id"])
            )
        )
        possible = [
            relation
            for fabric in ranked
            for relation in self.store.paper(fabric).relations
            if relation["relation"] == "possible_duplicate"
        ]
        snapshot = dict(
            plan_hash=plan_hash,
            offset=0,
            expires=time.time() + 900,
            outcomes=[o.model_dump(mode="json") for o in outcomes],
            data=dict(
                papers=summaries,
                selected_sources=selected,
                raw_count=received,
                canonical_count=len(ranked),
                duplicates_merged=max(0, valid - sum(len(x["editions"]) for x in ranked.values())),
                possible_duplicates=possible[:40],
                search_plan_id=plan_hash,
                exhaustive=False,
                filter_application="post_filter",
                candidate_limited=True,
            ),
        )
        return self._search_page(snapshot, request.limit)

    def _search_page(self, snapshot: dict, limit: int) -> Result:
        offset = snapshot["offset"]
        data = dict(snapshot["data"])
        all_papers = data["papers"]
        data["papers"] = all_papers[offset : offset + limit]
        result = result_with(
            data, [Outcome.model_validate(o) for o in snapshot["outcomes"]], bool(data["papers"])
        )
        result.meta.coverage = dict(
            selected_sources=data["selected_sources"],
            exhaustive=False,
            snapshot_candidates=len(all_papers),
        )
        if offset + limit < len(all_papers):
            cursor = new_id()
            self.store.cache_put(
                "cursor:" + cursor,
                {**snapshot, "offset": offset + limit},
                max(0, snapshot["expires"] - time.time()),
            )
            result.meta.next_cursor = cursor
            result.meta.truncated = True
        return result

    @operation
    async def get_paper(self, ref: str, **kwargs) -> Result:
        request = GetRequest(ref=ref, **kwargs)
        identifier = parse_ref(ref)
        outcomes = []
        if isinstance(identifier, str):
            paper = self.store.paper(identifier)
            editions = [self.store.edition(eid) for eid in paper.edition_ids]
        else:
            editions = self.store.lookup(identifier)
            observations = [
                r.retrieved_at
                for e in editions
                for r in self.store.records(e.edition_id)
                if r.provider != "user"
            ]
            stale_local = (
                bool(observations)
                and max(
                    datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
                    for value in observations
                )
                < time.time() - 86400
            )
            # Unversioned arXiv is resolved by the authoritative source unless
            # offline; cached versions are still explicitly returned.
            need_fetch = (
                request.refresh
                or not editions
                or stale_local
                or (
                    identifier.namespace == "arxiv"
                    and not identifier.version
                    and not self.config.offline
                )
            )
            if need_fetch:
                names = [
                    name
                    for name in self.config.sources
                    if self.providers[name].supports(identifier)
                ]
                if identifier.namespace == "arxiv":
                    names = ["arxiv"] if "arxiv" in self.config.sources else []
                if not names:
                    raise FabricError(
                        "unsupported_identifier", "No enabled provider can resolve this identifier."
                    )
                responses = await asyncio.gather(
                    *(
                        self._request(
                            name, identifier=identifier, refresh=request.refresh, timeout=10
                        )
                        for name in names[:3]
                    )
                )
                for records, outcome in responses:
                    outcomes.append(outcome)
                    for record in records:
                        self.store.ingest(record)
                editions = self.store.lookup(identifier)
            if not editions:
                return result_with(dict(paper=None, editions=[], resolved_ref=ref), outcomes, False)
            if identifier.namespace == "arxiv" and identifier.version is None:
                editions.sort(key=lambda e: int((e.version or "v0")[1:]), reverse=True)
            paper = self.store.paper(editions[0].fabric_id)
        if request.edition_id:
            if request.edition_id not in paper.edition_ids or (
                not isinstance(identifier, str)
                and request.edition_id not in {e.edition_id for e in editions}
            ):
                raise FabricError(
                    "invalid_argument",
                    "Requested edition does not match this paper reference or its explicit version.",
                )
            editions = [self.store.edition(request.edition_id)]
        resolved = editions[0] if len(editions) == 1 or not isinstance(identifier, str) else None
        if not isinstance(identifier, str) and identifier.namespace == "arxiv" and editions:
            resolved = editions[0]
        data = dict(
            paper=paper.model_dump(mode="json"),
            editions=[self._detail(self.store.edition(eid)) for eid in paper.edition_ids],
            selected_edition_id=resolved.edition_id if resolved else None,
            resolved_ref=("arxiv:" + identifier.value + (resolved.version or ""))
            if resolved and not isinstance(identifier, str) and identifier.namespace == "arxiv"
            else ref,
            resolved_at=now(),
            next_actions=["find_evidence", "export_citations"],
        )
        result = result_with(data, outcomes, True)
        if outcomes and all(o.status not in {"ok", "no_results"} for o in outcomes):
            result.meta.stale = True
            result.meta.cache_status = "stale"
            result.warnings.append(
                "Provider resolution was incomplete; retained local metadata is being returned."
            )
        return result

    async def _select(
        self, selector: PaperSelector, *, local_only: bool = False
    ) -> tuple[Edition, list[Outcome]]:
        identifier = parse_ref(selector.ref)
        if local_only:
            if isinstance(identifier, str):
                editions = [self.store.edition(e) for e in self.store.paper(identifier).edition_ids]
            else:
                editions = self.store.lookup(identifier)
            if selector.edition_id:
                editions = [e for e in editions if e.edition_id == selector.edition_id]
            if len(editions) != 1:
                raise FabricError(
                    "ambiguous_reference" if editions else "unknown_reference",
                    "Resolve the paper first and choose an explicit edition before export.",
                )
            return editions[0], []
        result = await self.get_paper(**selector.model_dump())
        if result.status == "failed" or not result.data or not result.data.get("paper"):
            if result.errors:
                error = result.errors[0]
                raise FabricError(error.code, error.message, retryable=error.retryable)
            raise FabricError(
                "unknown_reference", "Selected sources have no matching paper record."
            )
        selected = result.data["selected_edition_id"]
        if selected is None:
            raise FabricError(
                "ambiguous_reference",
                "Multiple editions are available; get_paper lists their IDs. Specify edition_id.",
            )
        return self.store.edition(selected), result.outcomes

    @operation
    async def import_document(
        self, path: str | Path, edition_id: str | None = None, title: str | None = None
    ) -> Result:
        path = Path(path).expanduser().resolve()
        try:
            with path.open("rb") as file:
                raw = file.read(self.config.max_download_bytes + 1)
        except OSError as exc:
            raise FabricError(
                "permission_denied", "The selected local file cannot be read."
            ) from exc
        if len(raw) > self.config.max_download_bytes:
            raise FabricError("resource_limit", "Local file exceeds the import size limit.")
        is_pdf = raw.lstrip().startswith(b"%PDF-")
        if not is_pdf and path.suffix.lower() not in {".txt", ".md"}:
            raise FabricError("unsupported_content", "Import a PDF or UTF-8 .txt/.md file.")
        if edition_id:
            edition = self.store.edition(edition_id)
        else:
            matches = list(
                self.store.db.execute(
                    "SELECT DISTINCT edition_id FROM documents WHERE hash=?", (sha(raw),)
                )
            )
            if len(matches) > 1:
                raise FabricError(
                    "ambiguous_reference",
                    "These bytes are associated with multiple editions; specify --edition.",
                )
            edition = (
                self.store.edition(matches[0][0])
                if matches
                else self.store.ingest(
                    SourceRecord(
                        provider="user", source_id=sha(raw), title=title or path.stem, kind="other"
                    )
                )
            )
        doc, extraction = await ingest_document(
            self.store,
            self.config,
            edition,
            raw,
            media_type="application/pdf" if is_pdf else "text/plain",
            provider="local_import",
            source_uri="local-import:" + path.name,
            source_kind="full_text" if is_pdf else "user_text",
        )
        partial = bool(extraction and extraction.coverage.pages_failed)
        return Result(
            status="partial" if partial else "ok",
            data=dict(
                fabric_id=edition.fabric_id,
                edition_id=edition.edition_id,
                document=doc.model_dump(mode="json"),
                extraction_id=extraction.extraction_id if extraction else None,
            ),
            warnings=extraction.warnings if extraction else [],
        )

    async def _ensure_document(
        self, edition: Edition, allow_abstract: bool
    ) -> tuple[Outcome, list[str]]:
        documents = self.store.documents(edition.edition_id)
        full = [d for d in documents if d.source_kind != "abstract"]
        if full:
            return Outcome(
                scope="document", id=edition.edition_id, status="ok", cache_status="fresh"
            ), []
        if allow_abstract and documents:
            return Outcome(
                scope="document",
                id=edition.edition_id,
                status="partial",
                code="abstract_only",
                cache_status="fresh",
            ), ["Full text unavailable; abstract evidence only."]
        failures = []
        last_code = "document_unavailable"
        records = self.store.records(edition.edition_id)
        candidates: list[DocumentCandidate] = []
        for record in records:
            for candidate in record.candidates:
                if candidate.access_type == "open_access" and candidate.url not in [
                    c.url for c in candidates
                ]:
                    candidates.append(candidate)
        for candidate in candidates[:2]:
            # Never replace an explicit arXiv version by a different candidate.
            if edition.version and candidate.version != edition.version:
                last_code = "document_version_mismatch"
                failures.append("Candidate version does not match selected edition.")
                continue
            try:
                raw, url = await download(candidate, self.config)
                doc, extraction = await ingest_document(
                    self.store,
                    self.config,
                    edition,
                    raw,
                    media_type="application/pdf",
                    provider=candidate.provider,
                    source_uri=url,
                    candidate=candidate,
                )
                partial = bool(extraction and extraction.coverage.pages_failed)
                return Outcome(
                    scope="document",
                    id=edition.edition_id,
                    status="partial" if partial else "ok",
                    code="partial_page_extraction" if partial else None,
                ), failures
            except FabricError as exc:
                last_code = exc.code
                failures.append(f"{exc.code}: {exc.message}")
        if allow_abstract:
            for record in records:
                if record.abstract:
                    await ingest_document(
                        self.store,
                        self.config,
                        edition,
                        record.abstract.encode(),
                        media_type="text/plain",
                        provider=record.provider,
                        source_uri=record.source_uri or record.source_id,
                        source_kind="abstract",
                    )
                    return Outcome(
                        scope="document",
                        id=edition.edition_id,
                        status="partial",
                        code="abstract_only",
                    ), failures + ["Full text unavailable; abstract evidence only."]
        return Outcome(
            scope="document",
            id=edition.edition_id,
            status="unavailable",
            code=last_code,
        ), failures

    @operation
    async def find_evidence(self, papers: list, query: str, **kwargs) -> Result:
        request = EvidenceRequest(papers=papers, query=query, **kwargs)
        if not query.strip():
            raise FabricError("invalid_argument", "Query must not be blank.")
        outcomes, warnings, editions = [], [], []

        async def prepare(selector):
            try:
                async with asyncio.timeout(self.config.evidence_timeout):
                    edition, provider_outcomes = await self._select(selector)
                    outcome, notices = await self._ensure_document(edition, request.allow_abstract)
                    return edition, [*provider_outcomes, outcome], notices
            except (FabricError, TimeoutError) as exc:
                code = exc.code if isinstance(exc, FabricError) else "document_timeout"
                return (
                    None,
                    [Outcome(scope="paper", id=selector.ref, status="unavailable", code=code)],
                    [],
                )

        for edition, items, notices in await asyncio.gather(*(prepare(s) for s in request.papers)):
            outcomes.extend(items)
            warnings.extend(notices)
            if edition:
                editions.append(edition)
        hits: list[dict[str, Any]] = []
        size = 0
        counts: defaultdict[str, int] = defaultdict(int)
        coverages: dict[str, Any] = {}
        structured_meta: dict[str, Any] = {}
        selected_rows: list[dict[str, Any]] = []
        truncated = False
        if request.retrieval_policy == "structured_v3":
            try:
                selected_rows, structured_meta = await structured_retrieve(
                    self.store, [e.edition_id for e in editions], request
                )
                plan = structured_meta["query_plan"]
                trace = structured_meta["selection_trace"]
                truncated = bool(trace["budget_rejected_candidates"])
                if trace.get("outcome_code"):
                    outcomes.append(
                        Outcome(
                            scope="retrieval",
                            id="structured_v3",
                            status="partial",
                            code=trace["outcome_code"],
                        )
                    )
            except (FabricError, TimeoutError) as exc:
                warnings.append("Structured index unavailable; falling back to v2 retrieval.")
                outcomes.append(
                    Outcome(
                        scope="retrieval",
                        id="structured_v3",
                        status="partial",
                        code="structure_index_unavailable",
                    )
                )
                structured_meta = {
                    "requested_policy": "structured_v3",
                    "fallback_reason": getattr(exc, "code", "structure_index_timeout"),
                }
        if not structured_meta.get("structure_index_version"):
            plan = query_plan(query, request.expand_query)
            rows = self.store.passage_search([e.edition_id for e in editions], plan["expanded"])
            if plan["mappings"]:
                rows.sort(
                    key=lambda row: (-concept_coverage(row["text"], plan), row["score"], row["id"])
                )
            if plan["contains_chinese"]:
                warnings.append(
                    "Chinese query support is limited to an optional research glossary, not semantic translation. "
                    "Inspect query_plan and try explicit English terms for uncovered concepts."
                )
            truncated = False
            selected_rows = []
            for row in rows:
                if counts[row["edition_id"]] >= 4:
                    truncated = True
                    continue
                extraction = self.store.extraction(row["extraction_id"])
                if not request.allow_abstract and extraction.coverage.source_kind == "abstract":
                    continue
                coverages[extraction.document_id] = extraction.coverage.model_dump(mode="json")
                if (
                    size + len(row["text"]) > request.max_chars
                    or len(selected_rows) >= request.max_passages
                ):
                    truncated = True
                    continue
                selected_rows.append(row)
                size += len(row["text"])
                counts[row["edition_id"]] += 1
            if request.include_context:
                selected_rows = with_context(self.store, selected_rows, request.max_chars)
        if structured_meta.get("structure_index_version") and plan["contains_chinese"]:
            warnings.append(
                "Chinese query support uses a limited research glossary, not semantic translation."
            )
        for row in selected_rows:
            try:
                evidence = evidence_from_passage(self.store, row)
            except FabricError as exc:
                outcomes.append(
                    Outcome(scope="evidence", id=row["id"], status="parse_failed", code=exc.code)
                )
                continue
            hits.append(
                dict(
                    evidence=evidence.model_dump(mode="json"),
                    retrieval_score=-row["score"],
                    retrieval_method="fts5-bm25-v1",
                    context_expanded=row["id"] not in row.get("seed_ids", [row["id"]]),
                    score_basis=row.get("score_basis")
                    or (
                        "derived_block_bm25; not semantic confidence"
                        if structured_meta.get("structure_index_version")
                        and row.get("origin") != "passage"
                        else "seed_passage_bm25; not semantic confidence"
                    ),
                    **(
                        {"seed_block_ids": row.get("seed_ids", [])}
                        if structured_meta.get("structure_index_version")
                        and row.get("origin") != "passage"
                        else {"seed_passage_ids": row.get("seed_ids", [row["id"]])}
                    ),
                    lexical_concept_coverage=concept_coverage(row["text"], plan),
                    quality_flags=quality_flags(row["text"]),
                )
            )
        for edition in editions:
            for doc in self.store.documents(edition.edition_id):
                if not request.allow_abstract and doc.source_kind == "abstract":
                    continue
                for row in self.store.db.execute(
                    "SELECT id FROM extractions WHERE document_id=?", (doc.document_id,)
                ):
                    extraction = self.store.extraction(row[0])
                    coverages[doc.document_id] = extraction.coverage.model_dump(mode="json")
                    if extraction.coverage.pages_failed:
                        outcomes.append(
                            Outcome(
                                scope="extraction",
                                id=extraction.extraction_id,
                                status="partial",
                                code="partial_page_extraction",
                            )
                        )
        result = result_with(
            dict(
                hits=hits,
                paper_outcomes=[
                    o.model_dump(mode="json") for o in outcomes if o.scope != "provider"
                ],
                coverage=coverages,
                retrieval_method="fts5-bm25",
                retrieval_version="3" if structured_meta.get("structure_index_version") else "2",
                rerank_method=(
                    "region-conditions-v1"
                    if structured_meta.get("structure_index_version")
                    else "weighted_glossary_coverage-v1"
                    if plan["mappings"]
                    else "none"
                ),
                query_plan=plan,
                context_policy=(
                    "role-regions-v1"
                    if structured_meta.get("structure_index_version")
                    else "same-page-bounded-v1"
                )
                if request.include_context
                else "none",
                returned_chars=sum(len(hit["evidence"]["excerpt"]) for hit in hits),
                **{k: v for k, v in structured_meta.items() if k != "query_plan"},
                **(
                    {
                        "bundles": bundles_for(selected_rows, hits, plan),
                    }
                    if structured_meta.get("structure_index_version")
                    else {}
                ),
            ),
            outcomes,
            bool(hits),
            warnings=warnings,
        )
        result.meta.truncated = truncated
        result.meta.coverage = dict(
            documents=coverages,
            query_language_support="lexical with optional research glossary; no semantic translation",
        )
        return result

    @operation
    async def verify_claim(self, claim: str, papers: list, **kwargs) -> Result:
        request = VerifyRequest(claim=claim, papers=papers, **kwargs)
        if not claim.strip():
            raise FabricError("invalid_argument", "Claim must not be blank.")
        evidence, outcomes, warnings = [], [], []
        if request.evidence_ids is None:
            retrieved = await self.find_evidence(papers=papers, query=claim[:2000])
            outcomes.extend(retrieved.outcomes)
            warnings.extend(retrieved.warnings)
            evidence = [
                self.store.evidence(hit["evidence"]["evidence_id"])
                for hit in (retrieved.data or {}).get("hits", [])
            ]
        else:
            evidence = [self.store.evidence(identifier) for identifier in request.evidence_ids]
        editions: list[Edition] = []
        for selector in request.papers:
            try:
                edition, resolution_outcomes = await self._select(selector)
                outcomes.extend(resolution_outcomes)
                if edition.edition_id not in [e.edition_id for e in editions]:
                    editions.append(edition)
            except FabricError as exc:
                outcomes.append(
                    Outcome(scope="paper", id=selector.ref, status="unavailable", code=exc.code)
                )
        if any(e.edition_id not in {edition.edition_id for edition in editions} for e in evidence):
            raise FabricError(
                "invalid_argument", "Evidence does not belong to the selected paper editions."
            )
        claim_obj = Claim(text=claim, context=request.context)
        receipts = []
        for edition in editions:
            items = [e for e in evidence if e.edition_id == edition.edition_id]
            limitations = [
                "No semantic verifier is installed in 0.1; lexical relevance is not claim support."
            ]
            if any(
                self.store.document(e.document_id).binding["status"] != "verified" for e in items
            ):
                limitations.append("Document version binding has not been independently verified.")
            assessment = ClaimAssessment(
                claim_id=claim_obj.claim_id,
                edition_id=edition.edition_id,
                verdict="unavailable",
                reason_code="verifier_not_configured",
                evidence_relations=[
                    dict(evidence_id=e.evidence_id, relation="context") for e in items
                ],
                rationale="Grounding checks are separate from semantic claim assessment. No support verdict was produced.",
                limitations=limitations,
                coverage=dict(
                    scope="supplied_evidence_only"
                    if request.evidence_ids
                    else "bounded_lexical_retrieval",
                    documents=list(dict.fromkeys(e.document_id for e in items)),
                    evidence_ids=[e.evidence_id for e in items],
                ),
                verifier=dict(
                    backend="none",
                    model=None,
                    model_revision=None,
                    prompt_hash=None,
                    policy_version="abstain-without-backend-v1",
                ),
            )
            receipt = EvidenceReceipt(
                claim_snapshot=claim_obj,
                metadata_snapshot_ids=[edition.metadata_snapshot_id],
                assessment=assessment,
                evidence_ids=[e.evidence_id for e in items],
                document_hashes={e.document_id: e.source_hash for e in items},
                identity_assessments=[
                    dict(
                        status=edition.identity_status,
                        scope=edition.edition_id,
                        source_record_ids=[
                            r.record_id for r in self.store.records(edition.edition_id)
                        ],
                        method="exact_provider_identifiers"
                        if edition.identity_status == "verified"
                        else "unverified",
                        checked_at=now(),
                        conflicts=[],
                    )
                ],
                grounding_status="verified" if items else "not_checked",
                verification_config_hash=sha(b'{"backend":"none"}'),
            )
            self.store.save_receipt(receipt)
            receipts.append(receipt.model_dump(mode="json"))
        outcomes.append(
            Outcome(
                scope="verifier", id="none", status="not_configured", code="verifier_not_configured"
            )
        )
        # A receipt saying "unavailable" is not itself a successful assessment.
        return Result(
            status="partial" if evidence else "failed",
            data=dict(
                receipts=receipts,
                evidence=[e.model_dump(mode="json") for e in evidence],
                paper_outcomes=[o.model_dump(mode="json") for o in outcomes],
                coverage=dict(
                    scope="supplied_evidence_only"
                    if request.evidence_ids
                    else "bounded_lexical_retrieval"
                ),
                limitations=["Semantic claim verification is unavailable in 0.1."],
            ),
            outcomes=outcomes,
            errors=[outcome_error(o) for o in outcomes if o.status not in {"ok", "no_results"}],
            warnings=warnings,
        )

    @operation
    async def export_citations(self, papers: list, format: str = "bibtex", **kwargs) -> Result:
        request = ExportRequest.model_validate(dict(papers=papers, format=format, **kwargs))
        if format not in {"bibtex", "csl_json"}:
            return Result(
                status="failed",
                data={"available_formats": ["bibtex", "csl_json"]},
                errors=[
                    ErrorDetail(
                        code="unsupported_format", message="APA and IEEE are planned for 0.2."
                    )
                ],
            )
        receipts = [self.store.receipt(identifier) for identifier in request.receipt_ids or []]
        entries, manifests, outcomes, warnings, rendered, selected = [], [], [], [], [], []
        for selector in request.papers:
            try:
                edition, _ = await self._select(selector, local_only=True)
                if edition.edition_id in selected:
                    continue
                selected.append(edition.edition_id)
                matching = [r for r in receipts if r.assessment.edition_id == edition.edition_id]
                # Validate current availability, while rendering the metadata version
                # retained in the receipt so historical citations remain stable.
                snapshots = {mid for receipt in matching for mid in receipt.metadata_snapshot_ids}
                if len(snapshots) > 1:
                    raise FabricError(
                        "ambiguous_reference",
                        "Receipts use different metadata snapshots; export them separately.",
                    )
                for receipt in matching:
                    for eid in receipt.evidence_ids:
                        self.store.evidence(eid)
                metadata = self.store.metadata(
                    next(iter(snapshots)) if snapshots else edition.metadata_snapshot_id
                )
                if metadata.edition_id != edition.edition_id:
                    raise FabricError(
                        "evidence_integrity_failed",
                        "Citation metadata belongs to a different edition.",
                    )
                entries.append(citations.csl(edition, metadata))
                rendered.append(citations.bibtex(edition, metadata))
                records = self.store.records(edition.edition_id)
                manifests.append(
                    dict(
                        edition_id=edition.edition_id,
                        metadata_snapshot_id=metadata.snapshot_id,
                        identity_status=edition.identity_status,
                        receipt_ids=[r.receipt_id for r in matching],
                        grounding_status="verified"
                        if matching and all(r.grounding_status == "verified" for r in matching)
                        else "not_checked",
                        claim_assessment_status="unavailable" if matching else "not_checked",
                        claim_verdicts=[
                            dict(claim_id=r.claim_snapshot.claim_id, verdict=r.assessment.verdict)
                            for r in matching
                        ],
                        retrieved_from=[
                            dict(
                                provider=r.provider,
                                source_uri=r.source_uri,
                                retrieved_at=r.retrieved_at,
                            )
                            for r in records
                        ],
                    )
                )
                if not metadata.authors or metadata.issued.year is None:
                    warnings.append(
                        f"Missing author or date metadata for edition {edition.edition_id}; no values invented."
                    )
                outcomes.append(Outcome(scope="citation", id=edition.edition_id, status="ok"))
            except FabricError as exc:
                outcomes.append(
                    Outcome(scope="citation", id=selector.ref, status="unavailable", code=exc.code)
                )
        if any(r.assessment.edition_id not in selected for r in receipts):
            raise FabricError(
                "invalid_argument", "A supplied receipt belongs to an edition outside this export."
            )
        return result_with(
            dict(
                format=format,
                content=entries if format == "csl_json" else "\n\n".join(rendered),
                items=entries,
                provenance_manifest=manifests,
            ),
            outcomes,
            bool(entries),
            warnings=warnings,
        )

    @operation
    async def doctor(self, online: bool = False) -> Result:
        self.store.db.execute("SELECT count(*) FROM passages_fts").fetchone()
        data = dict(
            version="0.1.0",
            sqlite_fts5=True,
            offline=self.config.offline,
            sources=self.config.sources,
            verifier="not_configured",
            supported_formats=["bibtex", "csl_json"],
            api_keys=dict(
                openalex=bool(self.config.openalex_api_key),
                semantic_scholar=bool(self.config.semantic_scholar_api_key),
            ),
        )
        if online:
            probe = await self.search_papers("attention", limit=1)
            return result_with(
                data, probe.outcomes, any(o.status in {"ok", "no_results"} for o in probe.outcomes)
            )
        return Result(data=data)

    async def read_resource(self, uri: str) -> Result:
        prefix = "citefabric://"
        if not uri.startswith(prefix):
            return FabricError("invalid_argument", "Unknown resource scheme.").result()
        try:
            kind, identifier = uri[len(prefix) :].split("/", 1)
            if kind == "papers":
                return await self.get_paper("fabric:" + identifier)
            if kind == "evidence":
                return Result(
                    data={"evidence": self.store.evidence(identifier).model_dump(mode="json")}
                )
            if kind == "receipts":
                receipt = self.store.receipt(identifier)
                availability = "available"
                for eid in receipt.evidence_ids:
                    try:
                        self.store.evidence(eid)
                    except FabricError:
                        availability = "source_unavailable"
                return Result(
                    data=dict(receipt=receipt.model_dump(mode="json"), availability=availability)
                )
            if kind == "results":
                result = self.store.cache_get("result:" + identifier)
                if result:
                    return Result.model_validate(result[0])
            raise FabricError("unknown_reference", "Resource not found.")
        except (ValueError, FabricError) as exc:
            return (
                exc.result()
                if isinstance(exc, FabricError)
                else FabricError("invalid_argument", "Invalid resource URI.").result()
            )
