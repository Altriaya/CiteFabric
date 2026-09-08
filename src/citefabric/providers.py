"""Discovery adapters normalize metadata without claiming full-text availability."""

from __future__ import annotations

import html
import json
import re
import time
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from .identity import arxiv_id, normalize_doi
from .models import (
    Author,
    DocumentCandidate,
    ExternalID,
    FabricError,
    Issued,
    Outcome,
    SourceRecord,
    sha,
)
from .runtime import ProviderFailure, ProviderRuntime


def clean(value) -> str:
    return html.unescape(re.sub(r"<[^>]*>", " ", str(value or ""))).strip()


def first(value, default=None):
    return value[0] if isinstance(value, list) and value else default


def doi(value) -> list[ExternalID]:
    if not value:
        return []
    try:
        return [ExternalID(namespace="doi", value=normalize_doi(value))]
    except FabricError:
        return []


def issued_parts(parts) -> Issued:
    if not isinstance(parts, list):
        return Issued()
    return Issued(**dict(zip(("year", "month", "day"), parts[:3], strict=False)))


def crossref(record: dict) -> SourceRecord:
    ids = doi(record.get("DOI"))
    if not ids:
        raise ValueError("missing DOI")
    date = record.get("published") or record.get("issued") or record.get("published-online") or {}
    authors = []
    for a in record.get("author", []):
        display = a.get("name") or " ".join(x for x in [a.get("given"), a.get("family")] if x)
        if display:
            authors.append(
                Author(
                    display_name=display,
                    given=a.get("given"),
                    family=a.get("family"),
                    orcid=a.get("ORCID"),
                    organization=a.get("name"),
                )
            )
    return SourceRecord(
        provider="crossref",
        source_id=ids[0].value,
        title=clean(first(record.get("title"), "")),
        authors=authors,
        issued=issued_parts(first(date.get("date-parts"))),
        venue=first(record.get("container-title")),
        kind={
            "journal-article": "journal_article",
            "proceedings-article": "conference_paper",
            "posted-content": "preprint",
        }.get(record.get("type", ""), "other"),
        external_ids=ids,
        abstract=clean(record.get("abstract")) or None,
        source_uri="https://api.crossref.org/works/" + quote(ids[0].value, safe=""),
    )


def openalex(record: dict) -> SourceRecord:
    source_id = str(record["id"]).rsplit("/", 1)[-1]
    ids = doi(record.get("doi"))
    ids.append(ExternalID(namespace="openalex", value=source_id))
    inverted = record.get("abstract_inverted_index") or {}
    positions = {}
    for word, offsets in inverted.items():
        for offset in offsets:
            if isinstance(offset, int) and 0 <= offset < 100000:
                positions[offset] = word
    abstract = " ".join(positions[x] for x in sorted(positions)) or None
    oa = record.get("open_access") or {}
    candidates: list[DocumentCandidate] = []
    for location in [record.get("best_oa_location"), *(record.get("locations") or [])]:
        if location and location.get("is_oa") is True and location.get("pdf_url"):
            candidate = DocumentCandidate(
                url=location["pdf_url"],
                provider="openalex",
                version=location.get("version"),
                license=location.get("license"),
                access_type="open_access",
            )
            if candidate.url not in [c.url for c in candidates]:
                candidates.append(candidate)
    return SourceRecord(
        provider="openalex",
        source_id=source_id,
        title=clean(record.get("title")),
        authors=[
            Author(display_name=a["author"]["display_name"], orcid=a["author"].get("orcid"))
            for a in record.get("authorships", [])
            if a.get("author", {}).get("display_name")
        ],
        issued=Issued(year=record.get("publication_year")),
        venue=((record.get("primary_location") or {}).get("source") or {}).get("display_name"),
        external_ids=ids,
        abstract=abstract,
        candidates=candidates[:5],
        open_access=oa.get("is_oa"),
        publication_status="retracted" if record.get("is_retracted") else "unknown",
        source_uri=str(record["id"]),
    )


def semantic_scholar(record: dict) -> SourceRecord:
    source_id = record["paperId"]
    external = record.get("externalIds") or {}
    ids = doi(external.get("DOI"))
    related = []
    if external.get("ArXiv"):
        identifier = arxiv_id(external["ArXiv"])
        if ids:
            related.append(identifier)
        else:
            ids.append(identifier)
    ids.append(ExternalID(namespace="s2", value=source_id))
    pdf = record.get("openAccessPdf") or {}
    candidates = (
        [
            DocumentCandidate(
                url=pdf["url"],
                provider="semantic_scholar",
                license=pdf.get("license"),
                access_type="open_access",
            )
        ]
        if pdf.get("url")
        else []
    )
    return SourceRecord(
        provider="semantic_scholar",
        source_id=source_id,
        title=clean(record.get("title")),
        authors=[
            Author(display_name=a["name"]) for a in record.get("authors", []) if a.get("name")
        ],
        issued=Issued(year=record.get("year")),
        venue=record.get("venue") or None,
        external_ids=ids,
        related_ids=related,
        abstract=record.get("abstract"),
        candidates=candidates,
        open_access=record.get("isOpenAccess"),
        source_uri="https://www.semanticscholar.org/paper/" + source_id,
    )


def arxiv_entries(text: str) -> list[SourceRecord]:
    root = ElementTree.fromstring(text)
    ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
    records = []
    for entry in root.findall("a:entry", ns):
        source = entry.findtext("a:id", "", ns)
        if "/api/errors" in source:
            raise ValueError("arXiv API error feed")
        identifier = arxiv_id(source)
        version = identifier.version
        date = entry.findtext("a:published", "", ns)[:10]
        parts = [int(x) for x in date.split("-")] if date else []
        url = "https://arxiv.org/pdf/" + identifier.value + (version or "")
        records.append(
            SourceRecord(
                provider="arxiv",
                source_id=identifier.value + (version or ""),
                title=" ".join(entry.findtext("a:title", "", ns).split()),
                authors=[
                    Author(display_name=a.findtext("a:name", "", ns))
                    for a in entry.findall("a:author", ns)
                ],
                issued=issued_parts(parts),
                venue=entry.findtext("x:journal_ref", None, ns),
                kind="preprint",
                version=version,
                external_ids=[identifier],
                related_ids=doi(entry.findtext("x:doi", None, ns)),
                abstract=entry.findtext("a:summary", None, ns),
                candidates=[
                    DocumentCandidate(
                        url=url, provider="arxiv", version=version, access_type="open_access"
                    )
                ],
                open_access=True,
                source_uri="https://arxiv.org/abs/" + identifier.value + (version or ""),
            )
        )
    return records


class DiscoveryProvider:
    def __init__(self, name: str, runtime: ProviderRuntime):
        self.name, self.runtime = name, runtime

    def supports(self, identifier: ExternalID) -> bool:
        return (
            identifier.namespace
            in {
                "crossref": {"doi"},
                "arxiv": {"arxiv"},
                "openalex": {"doi", "openalex"},
                "semantic_scholar": {"doi", "arxiv", "s2"},
            }[self.name]
        )

    def endpoint(self, query: str | None = None, identifier: ExternalID | None = None):
        config = self.runtime.config
        headers = {}
        params: dict = {}
        if self.name == "crossref":
            url = "https://api.crossref.org/works"
            if identifier:
                url += "/" + quote(identifier.value, safe="")
            else:
                params.update({"query.bibliographic": query, "rows": 20})
            if config.contact_email:
                params["mailto"] = config.contact_email
        elif self.name == "arxiv":
            url = "https://export.arxiv.org/api/query"
            if identifier:
                params["id_list"] = identifier.value + (identifier.version or "")
            else:
                # Query is data; do not expose unbounded upstream query syntax.
                terms = re.findall(r"\w+", query or "")[:32]
                if not terms:
                    raise FabricError(
                        "invalid_argument", "Query needs at least one searchable term."
                    )
                params.update(
                    search_query=" AND ".join('all:"' + word + '"' for word in terms),
                    max_results=20,
                    sortBy="relevance",
                )
        elif self.name == "openalex":
            url = "https://api.openalex.org/works"
            if identifier:
                suffix = (
                    "https://doi.org/" + identifier.value
                    if identifier.namespace == "doi"
                    else identifier.value
                )
                url += "/" + quote(suffix, safe="")
            else:
                params.update(search=query, per_page=20)
            if config.openalex_api_key:
                headers["Authorization"] = "Bearer " + config.openalex_api_key.get_secret_value()
        else:
            url = "https://api.semanticscholar.org/graph/v1/paper/"
            if identifier:
                prefix = {"doi": "DOI:", "arxiv": "ARXIV:", "s2": ""}[identifier.namespace]
                # S2 cannot resolve a precise arXiv version; only arXiv does that.
                url += quote(prefix + identifier.value, safe="")
            else:
                url += "search"
                params.update(query=query, limit=20)
            params["fields"] = (
                "paperId,title,authors,year,venue,externalIds,abstract,openAccessPdf,isOpenAccess"
            )
            if config.semantic_scholar_api_key:
                headers["x-api-key"] = config.semantic_scholar_api_key.get_secret_value()
        return url, params, headers

    async def request(
        self,
        *,
        query: str | None = None,
        identifier: ExternalID | None = None,
        refresh: bool = False,
    ) -> tuple[list[SourceRecord], Outcome]:
        start = time.monotonic()
        outcome = Outcome(id=self.name, status="unavailable")
        try:
            url, params, headers = self.endpoint(query, identifier)
            fetched = await self.runtime.fetch(
                self.name,
                url,
                params,
                headers=headers,
                ttl=86400 if identifier else 900,
                refresh=refresh,
            )
            outcome.cache_status = fetched.cache_status
            outcome.attempts = fetched.attempts
            invalid = 0
            if self.name == "arxiv":
                records = arxiv_entries(fetched.text)
                received = len(records)
            else:
                body = json.loads(fetched.text)
                if (
                    not isinstance(body, dict)
                    or body.get("error")
                    or body.get("message-type") == "error"
                ):
                    raise ValueError("invalid provider payload")
                if self.name == "crossref":
                    message = body["message"]
                    items = [message] if identifier else message["items"]
                    normalize = crossref
                elif self.name == "openalex":
                    items = [body] if identifier else body["results"]
                    normalize = openalex
                else:
                    items = [body] if identifier else body["data"]
                    normalize = semantic_scholar
                if not isinstance(items, list):
                    raise ValueError("expected provider list")
                received, records = len(items), []
                for item in items[:20]:
                    try:
                        records.append(normalize(item))
                    except (ValueError, TypeError, KeyError, FabricError):
                        invalid += 1
            if identifier:
                records = [
                    r
                    for r in records
                    if any(
                        e.namespace == identifier.namespace
                        and e.value == identifier.value
                        and (identifier.version is None or e.version == identifier.version)
                        for e in r.external_ids
                    )
                ]
                if received and not records and not invalid:
                    raise ValueError("provider returned a different identifier or version")
            for record in records:
                record.retrieved_at = fetched.retrieved_at
                record.record_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"{self.name}:{record.source_id}:{fetched.retrieved_at}:{sha(fetched.text.encode())}",
                    )
                )
            outcome.records_received, outcome.records_valid = received, len(records)
            outcome.status = (
                "partial"
                if invalid and records
                else "parse_failed"
                if invalid
                else "ok"
                if records
                else "no_results"
            )
            outcome.code = "invalid_provider_records" if invalid else fetched.degraded_code
            if fetched.degraded_code:
                outcome.status = "partial"
            if not invalid and fetched.cache_status == "miss":
                self.runtime.acknowledge(
                    self.name,
                    url,
                    params,
                    headers,
                    fetched.text,
                    86400 if identifier else 900,
                    fetched.retrieved_at,
                )
            return records, outcome
        except ProviderFailure as exc:
            outcome.status, outcome.code = exc.status, exc.code
            outcome.retryable, outcome.retry_after_seconds, outcome.attempts = (
                exc.retryable,
                exc.retry_after,
                exc.attempts,
            )
        except (ValueError, KeyError, TypeError, ElementTree.ParseError, DefusedXmlException):
            outcome.status, outcome.code = "parse_failed", "invalid_provider_response"
        finally:
            outcome.elapsed_ms = int((time.monotonic() - start) * 1000)
        return [], outcome
