"""Version-bound documents, controlled downloads, and exact text grounding."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import sqlite3
import sys
from pathlib import Path

import httpx

from .config import Config
from .identity import normalized_title
from .models import (
    Coverage,
    Document,
    DocumentCandidate,
    Edition,
    EvidenceObject,
    ExtractionSnapshot,
    FabricError,
    Locator,
    LocatorKind,
    RetrievalEvent,
    SourceKind,
    TextUnit,
    now,
    sha,
)
from .storage import Store


async def public_address(url: httpx.URL) -> str:
    if url.scheme not in {"http", "https"} or not url.host or url.userinfo:
        raise FabricError(
            "permission_denied", "Document URLs must be public HTTP(S) URLs without credentials."
        )
    if url.port not in {None, 80, 443}:
        raise FabricError("permission_denied", "Document download ports are limited to HTTP(S).")
    try:
        entries = await asyncio.to_thread(
            socket.getaddrinfo,
            url.host,
            url.port or (443 if url.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
        addresses = list(dict.fromkeys(str(entry[4][0]) for entry in entries))
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise FabricError(
                "permission_denied",
                "Private, local and special-purpose document addresses are not allowed.",
            )
        return addresses[0]
    except (socket.gaierror, ValueError) as exc:
        raise FabricError(
            "document_unavailable", "Could not resolve the document host.", retryable=True
        ) from exc


async def download(candidate: DocumentCandidate, config: Config) -> tuple[bytes, str]:
    if config.offline:
        raise FabricError("offline", "Document downloads are disabled in offline mode.")
    try:
        url = httpx.URL(candidate.url)
        # One pool per hop prevents two hostnames resolving to the same address
        # from sharing a connection with a different TLS SNI identity.
        async with asyncio.timeout(min(20, config.evidence_timeout)):
            for _ in range(6):
                address = await public_address(url)
                pinned = url.copy_with(host=address)
                host_header = url.netloc.decode("ascii")
                async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
                    async with client.stream(
                        "GET",
                        pinned,
                        headers={
                            "Host": host_header,
                            "User-Agent": "CiteFabric/0.1",
                            "Accept": "application/pdf",
                        },
                        extensions={"sni_hostname": url.host},
                        timeout=15,
                    ) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise FabricError(
                                    "document_unavailable", "Document redirect has no destination."
                                )
                            url = url.join(location)
                            continue
                        if response.status_code in {401, 403}:
                            raise FabricError(
                                "permission_denied",
                                "The document requires access not available to CiteFabric.",
                            )
                        if response.status_code != 200:
                            raise FabricError(
                                "document_unavailable",
                                f"Document server returned HTTP {response.status_code}.",
                                retryable=response.status_code in {429, 500, 502, 503, 504},
                            )
                        length = response.headers.get("content-length")
                        if length and int(length) > config.max_download_bytes:
                            raise FabricError(
                                "resource_limit", "Document exceeds download size limit."
                            )
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > config.max_download_bytes:
                                raise FabricError(
                                    "resource_limit", "Document exceeds download size limit."
                                )
                            chunks.append(chunk)
                        content = b"".join(chunks)
                        if not content.lstrip().startswith(b"%PDF-"):
                            raise FabricError(
                                "unsupported_content",
                                "The download is not a PDF; login and landing pages are not evidence.",
                            )
                        return content, str(url)
            raise FabricError("document_unavailable", "Too many document redirects.")
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise FabricError(
            "document_unavailable", "Document download timed out.", retryable=True
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise FabricError(
            "document_unavailable", "Document download failed.", retryable=True
        ) from exc


async def parse_pdf(path: Path, config: Config) -> dict:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "citefabric.pdf_worker",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(
                json.dumps(dict(path=str(path), max_pages=config.max_pages)).encode()
            ),
            config.parse_timeout,
        )
        if process.returncode != 0:
            raise FabricError("parse_failed", "PDF parser process failed.")
        data = json.loads(stdout)
        if data.get("error"):
            raise FabricError(data["error"], "PDF text extraction could not complete.")
        if not data.get("units"):
            raise FabricError(
                "ocr_required", "No readable text layer was found; OCR is not included in 0.1."
            )
        return data
    except TimeoutError as exc:
        raise FabricError("resource_limit", "PDF parsing exceeded the process time limit.") from exc
    except (ValueError, KeyError) as exc:
        raise FabricError("parse_failed", "PDF parser returned invalid output.") from exc
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


async def ingest_document(
    store: Store,
    config: Config,
    edition: Edition,
    raw: bytes,
    *,
    media_type: str,
    provider: str,
    source_uri: str,
    source_kind: SourceKind = "full_text",
    candidate: DocumentCandidate | None = None,
) -> tuple[Document, ExtractionSnapshot | None]:
    if len(raw) > config.max_download_bytes:
        raise FabricError("resource_limit", "Document exceeds import size limit.")
    digest = sha(raw)
    for existing in store.documents(edition.edition_id):
        if existing.source_hash == digest:
            # Verify cached bytes, rather than trusting a stale filesystem path.
            if (
                not store.blob_path(digest).exists()
                or sha(store.blob_path(digest).read_bytes()) != digest
            ):
                raise FabricError(
                    "evidence_integrity_failed", "Cached document bytes are missing or changed."
                )
            cached = store.db.execute(
                "SELECT id FROM extractions WHERE document_id=? ORDER BY rowid DESC LIMIT 1",
                (existing.document_id,),
            ).fetchone()
            if cached is None:
                raise FabricError("parse_failed", "Cached document has no extraction snapshot.")
            return existing, store.extraction(cached[0])
    store.write_blob(raw)
    try:
        if media_type == "application/pdf":
            parsed = await parse_pdf(store.blob_path(digest), config)
            units = [TextUnit.model_validate(unit) for unit in parsed["units"]]
            coverage = Coverage(
                source_kind=source_kind,
                pages_total=parsed["pages_total"],
                pages_parsed=len(units),
                pages_failed=parsed["pages_failed"],
            )
            parser, parser_version = "pypdf", parsed["parser_version"]
            warnings = [
                "PDF reading order and text extraction may differ from the rendered page; no OCR or table interpretation."
            ]
        else:
            text = raw.decode("utf-8")
            if not text.strip():
                raise FabricError("parse_failed", "Document contains no text.")
            if len(raw) > 4 * 1024 * 1024:
                raise FabricError("resource_limit", "Extracted text exceeds the text budget.")
            units = [TextUnit(text_unit_id="unit:1", text=text)]
            coverage = Coverage(source_kind=source_kind)
            parser, parser_version, warnings = "plain_text", "1", []
        full_text = "\f".join(unit.text for unit in units)
        metadata = store.metadata(edition.metadata_snapshot_id)
        header = units[0].text[:6000]
        matching = []
        for identifier in edition.external_ids:
            token = identifier.value + (identifier.version or "")
            if token.lower() in header.lower():
                matching.append(identifier.model_dump(mode="json"))
        title_matches = normalized_title(metadata.title) in normalized_title(header)
        # Only exact arXiv version labels provide a strong automated binding in
        # this release. A DOI alone does not distinguish manuscript/publication.
        exact_arxiv = any(i["namespace"] == "arxiv" and i["version"] for i in matching)
        binding = (
            "verified"
            if exact_arxiv and title_matches and edition.identity_status == "verified"
            else "user_asserted"
            if provider == "local_import"
            else "unresolved"
        )
        document = Document(
            edition_id=edition.edition_id,
            media_type=media_type,
            byte_length=len(raw),
            source_hash=digest,
            version_label=edition.version,
            binding=dict(
                status=binding,
                method="header_identifier_and_title"
                if binding == "verified"
                else "explicit_import"
                if provider == "local_import"
                else "provider_candidate",
                matched_identifiers=matching,
                metadata_snapshot_id=metadata.snapshot_id,
                checked_at=now(),
                warnings=[]
                if binding == "verified"
                else ["Exact document version binding is not independently verified."],
            ),
            access=dict(
                access_type="local_user_file"
                if provider == "local_import"
                else "open_access"
                if candidate
                else "unknown",
                license=candidate.license if candidate else None,
                redistribution="unknown",
                basis=provider,
            ),
            retrieval_event_ids=[],
            source_kind=source_kind,
        )
        event = RetrievalEvent(
            document_id=document.document_id,
            provider=provider,
            source_uri=source_uri,
            license=candidate.license if candidate else None,
        )
        document.retrieval_event_ids = [event.event_id]
        extraction = ExtractionSnapshot(
            document_id=document.document_id,
            parser=parser,
            parser_version=parser_version,
            config_hash=sha(json.dumps(dict(max_pages=config.max_pages), sort_keys=True).encode()),
            text_snapshot=full_text,
            text_units=units,
            text_hash=sha(full_text.encode()),
            coverage=coverage,
            warnings=warnings,
        )
        try:
            store.save_document(document, event, extraction)
        except sqlite3.IntegrityError:
            # Another process may finish the same import while parsing runs.
            duplicates = [d for d in store.documents(edition.edition_id) if d.source_hash == digest]
            if not duplicates:
                raise
            return duplicates[0], None
        return document, extraction
    except UnicodeDecodeError as exc:
        raise FabricError("parse_failed", "Text imports must be UTF-8 encoded.") from exc


def evidence_from_passage(store: Store, row: dict) -> EvidenceObject:
    ext = store.extraction(row["extraction_id"])
    doc = store.document(ext.document_id)
    unit = next(u for u in ext.text_units if u.text_unit_id == row["unit_id"])
    excerpt = unit.text[row["start"] : row["end"]]
    kind: LocatorKind = (
        "pdf_text"
        if doc.media_type == "application/pdf"
        else "abstract"
        if doc.source_kind == "abstract"
        else "plain_text"
    )
    evidence = EvidenceObject(
        evidence_id=row["id"],
        fabric_id=store.edition(row["edition_id"]).fabric_id,
        edition_id=row["edition_id"],
        document_id=doc.document_id,
        extraction_id=ext.extraction_id,
        retrieval_event_id=doc.retrieval_event_ids[0],
        source_hash=doc.source_hash,
        text_hash=ext.text_hash,
        locator=Locator(
            kind=kind,
            page=unit.page,
            text_unit_id=unit.text_unit_id,
            char_start=row["start"],
            char_end=row["end"],
        ),
        excerpt=excerpt,
        excerpt_hash=sha(excerpt.encode()),
        source_kind=doc.source_kind,
        grounding=dict(
            status="verified",
            method="snapshot_slice_and_hash",
            checked_at=now(),
            limitations=ext.warnings,
        ),
        context_refs=[],
    )
    store.save_evidence(evidence)
    return store.evidence(evidence.evidence_id)
