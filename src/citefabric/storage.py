"""Local repositories; network operations never run inside these transactions."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from .identity import id_key, normalized_title, title_conflict
from .models import (
    Document,
    Edition,
    EvidenceObject,
    EvidenceReceipt,
    ExternalID,
    ExtractionSnapshot,
    FabricError,
    MetadataSnapshot,
    Paper,
    RetrievalEvent,
    SourceRecord,
    new_id,
    sha,
)

SCHEMA = """
CREATE TABLE papers(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE editions(id TEXT PRIMARY KEY, paper_id TEXT NOT NULL REFERENCES papers(id), payload TEXT NOT NULL);
CREATE TABLE metadata(id TEXT PRIMARY KEY, edition_id TEXT NOT NULL REFERENCES editions(id), payload TEXT NOT NULL);
CREATE TABLE source_records(id TEXT PRIMARY KEY, edition_id TEXT REFERENCES editions(id), payload TEXT NOT NULL);
CREATE TABLE external_ids(namespace TEXT, value TEXT, version TEXT NOT NULL, edition_id TEXT NOT NULL REFERENCES editions(id), PRIMARY KEY(namespace,value,version));
CREATE TABLE documents(id TEXT PRIMARY KEY, edition_id TEXT NOT NULL REFERENCES editions(id), hash TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0, touched REAL NOT NULL, payload TEXT NOT NULL, UNIQUE(edition_id,hash));
CREATE TABLE retrievals(id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id), payload TEXT NOT NULL);
CREATE TABLE extractions(id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id), payload TEXT NOT NULL);
CREATE TABLE passages(id TEXT PRIMARY KEY, extraction_id TEXT NOT NULL REFERENCES extractions(id), edition_id TEXT NOT NULL REFERENCES editions(id), unit_id TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL, text TEXT NOT NULL);
CREATE VIRTUAL TABLE passages_fts USING fts5(id UNINDEXED, text, tokenize='unicode61');
CREATE TABLE evidence(id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id), extraction_id TEXT NOT NULL REFERENCES extractions(id), payload TEXT NOT NULL);
CREATE TABLE receipts(id TEXT PRIMARY KEY, edition_id TEXT NOT NULL REFERENCES editions(id), payload TEXT NOT NULL);
CREATE TABLE receipt_evidence(receipt_id TEXT REFERENCES receipts(id), evidence_id TEXT REFERENCES evidence(id), PRIMARY KEY(receipt_id,evidence_id));
CREATE TABLE cache(key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE runtime(key TEXT PRIMARY KEY, next_at REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0, token TEXT, failures INTEGER NOT NULL DEFAULT 0, circuit_until REAL NOT NULL DEFAULT 0);
CREATE TABLE relations(id TEXT PRIMARY KEY, source_id TEXT NOT NULL, target_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE aliases(id TEXT PRIMARY KEY, target_id TEXT NOT NULL REFERENCES papers(id));
CREATE TABLE title_index(title TEXT NOT NULL, edition_id TEXT NOT NULL REFERENCES editions(id), PRIMARY KEY(title,edition_id));
PRAGMA user_version=1;
"""


def dump(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Store:
    def __init__(self, data_dir: Path, cache_bytes: int = 2 * 1024**3):
        self.root = data_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs = self.root / "blobs" / "sha256"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.cache_bytes = cache_bytes
        self.db = sqlite3.connect(self.root / "citefabric.sqlite3", timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            # An exclusive migration lock also protects simultaneous first starts.
            try:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 0:
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            self.db.execute(statement)
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
        elif version not in {1, 2}:
            self.db.close()
            raise FabricError(
                "unsupported_schema", "This database requires a different CiteFabric version."
            )
        if self.db.execute("PRAGMA user_version").fetchone()[0] == 1:
            if version == 1:
                backups = self.root / "backups"
                backups.mkdir(exist_ok=True)
                with sqlite3.connect(backups / f"schema-1-{time.time_ns()}.sqlite3") as backup:
                    self.db.backup(backup)
            try:
                self.db.execute("BEGIN IMMEDIATE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 1:
                    self.db.execute(
                        "CREATE TABLE structure_indexes(id TEXT PRIMARY KEY, extraction_id TEXT NOT NULL REFERENCES extractions(id), payload TEXT NOT NULL)"
                    )
                    self.db.execute(
                        "CREATE TABLE structure_blocks(id TEXT PRIMARY KEY, index_id TEXT NOT NULL REFERENCES structure_indexes(id), extraction_id TEXT NOT NULL, edition_id TEXT NOT NULL, unit_id TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL)"
                    )
                    self.db.execute("CREATE INDEX structure_by_index ON structure_blocks(index_id)")
                    self.db.execute(
                        "CREATE VIRTUAL TABLE structure_fts USING fts5(id UNINDEXED,text,tokenize='unicode61')"
                    )
                    self.db.execute("PRAGMA user_version=2")
                self.db.commit()
            except BaseException:
                self.db.rollback()
                self.db.close()
                raise

    def close(self):
        self.db.close()

    def _get(self, table: str, identifier: str):
        allowed = {
            "papers",
            "editions",
            "metadata",
            "documents",
            "retrievals",
            "extractions",
            "evidence",
            "receipts",
        }
        if table not in allowed:
            raise ValueError(table)
        row = self.db.execute(f"SELECT payload FROM {table} WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise FabricError("unknown_reference", f"No local {table} record for the requested ID.")
        return json.loads(row[0])

    def paper(self, identifier: str) -> Paper:
        alias = self.db.execute(
            "SELECT target_id FROM aliases WHERE id=?", (identifier,)
        ).fetchone()
        identifier = alias[0] if alias else identifier
        paper = Paper.model_validate(self._get("papers", identifier))
        paper.edition_ids = [
            row[0]
            for row in self.db.execute(
                "SELECT id FROM editions WHERE paper_id=? ORDER BY id", (identifier,)
            )
        ]
        paper.relations = [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT payload FROM relations WHERE source_id=? OR target_id=?",
                (identifier, identifier),
            )
        ]
        statuses = {self.edition(eid).identity_status for eid in paper.edition_ids}
        paper.identity_status = (
            "conflict"
            if "conflict" in statuses
            else "verified"
            if statuses == {"verified"}
            else "user_asserted"
            if statuses == {"user_asserted"}
            else "unresolved"
        )
        paper.preferred_edition_id = paper.edition_ids[0] if len(paper.edition_ids) == 1 else None
        return paper

    def edition(self, identifier: str) -> Edition:
        return Edition.model_validate(self._get("editions", identifier))

    def metadata(self, identifier: str) -> MetadataSnapshot:
        return MetadataSnapshot.model_validate(self._get("metadata", identifier))

    def records(self, edition_id: str) -> list[SourceRecord]:
        # Keep history in storage; the most recent observation per source drives the view.
        rows = self.db.execute(
            "SELECT payload FROM source_records WHERE edition_id=? ORDER BY rowid", (edition_id,)
        )
        latest = {}
        for row in rows:
            record = SourceRecord.model_validate_json(row[0])
            latest[(record.provider, record.source_id)] = record
        return list(latest.values())

    def lookup(self, external: ExternalID) -> list[Edition]:
        if external.namespace == "arxiv" and external.version is None:
            rows = self.db.execute(
                "SELECT edition_id FROM external_ids WHERE namespace=? AND value=?",
                (external.namespace, external.value),
            )
        else:
            rows = self.db.execute(
                "SELECT edition_id FROM external_ids WHERE namespace=? AND value=? AND version=?",
                id_key(external),
            )
        return [self.edition(row[0]) for row in rows]

    def _relation(self, a: str, b: str, relation: str, basis: str, status: str = "candidate"):
        if a == b:
            return
        key = sha(f"{a}|{b}|{relation}".encode())
        payload = dict(source_id=a, target_id=b, relation=relation, basis=basis, status=status)
        self.db.execute(
            "INSERT OR IGNORE INTO relations VALUES(?,?,?,?)", (key, a, b, dump(payload))
        )

    def ingest(self, record: SourceRecord) -> Edition:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            prior = self.db.execute(
                "SELECT edition_id FROM source_records WHERE id=?", (record.record_id,)
            ).fetchone()
            if prior and prior[0]:
                return self.edition(prior[0])
            matches = {}
            for ext in record.external_ids:
                row = self.db.execute(
                    "SELECT edition_id FROM external_ids WHERE namespace=? AND value=? AND version=?",
                    id_key(ext),
                ).fetchone()
                if row:
                    matches[row[0]] = self.edition(row[0])
            if matches:
                edition = next(iter(matches.values()))
                existing = self.metadata(edition.metadata_snapshot_id)
                old_dois = {e.value for e in edition.external_ids if e.namespace == "doi"}
                new_dois = {e.value for e in record.external_ids if e.namespace == "doi"}
                incompatible_doi = bool(old_dois and new_dois and old_dois != new_dois)
                if (
                    len(matches) > 1
                    or incompatible_doi
                    or title_conflict(existing.title, record.title)
                ):
                    # Quarantine conflicting records. Never overwrite a trusted identity or
                    # silently join two editions using a malformed provider bridge.
                    self.db.execute(
                        "INSERT OR IGNORE INTO source_records VALUES(?,NULL,?)",
                        (record.record_id, dump(record)),
                    )
                    edition.identity_status = "conflict"
                    self.db.execute(
                        "UPDATE editions SET payload=? WHERE id=?",
                        (dump(edition), edition.edition_id),
                    )
                    self._relation(
                        edition.fabric_id,
                        "source:" + record.record_id,
                        "possible_duplicate",
                        "conflicting_strong_identifier",
                        "disputed",
                    )
                    return edition
            else:
                # Explicitly versioned arXiv entries share a work, but not an edition.
                sibling = []
                for ext in record.external_ids:
                    if ext.namespace == "arxiv":
                        sibling = self.lookup(ext.model_copy(update={"version": None}))
                if sibling:
                    paper = self.paper(sibling[0].fabric_id)
                else:
                    paper = Paper()
                    self.db.execute(
                        "INSERT INTO papers VALUES(?,?)", (paper.fabric_id, dump(paper))
                    )
                edition = Edition(
                    fabric_id=paper.fabric_id,
                    kind=record.kind,
                    version=record.version,
                    metadata_snapshot_id=new_id(),
                )
                self.db.execute(
                    "INSERT INTO editions VALUES(?,?,?)",
                    (edition.edition_id, edition.fabric_id, dump(edition)),
                )

            self.db.execute(
                "INSERT OR IGNORE INTO source_records VALUES(?,?,?)",
                (record.record_id, edition.edition_id, dump(record)),
            )
            by_key = {id_key(x): x for x in edition.external_ids}
            for ext in record.external_ids:
                ext = ext.model_copy(deep=True)
                ext.source_record_ids = sorted(
                    set(by_key.get(id_key(ext), ext).source_record_ids + [record.record_id])
                )
                by_key[id_key(ext)] = ext
                self.db.execute(
                    "INSERT OR IGNORE INTO external_ids VALUES(?,?,?,?)",
                    (*id_key(ext), edition.edition_id),
                )
            edition.external_ids = list(by_key.values())
            records = self.records(edition.edition_id)
            priority = {"crossref": 0, "arxiv": 0, "openalex": 2, "semantic_scholar": 3, "user": 5}
            records.sort(key=lambda r: (priority.get(r.provider, 4), r.provider, r.source_id))
            selected = records[0]
            fields = {}
            provenance = {}
            conflicts = []
            for name in ("title", "authors", "issued", "venue"):
                candidates = []
                for rec in records:
                    value = rec.model_dump(mode="json")[name]
                    if value and not (name == "issued" and value["year"] is None):
                        candidates.append(
                            dict(
                                value=value,
                                provider=rec.provider,
                                source_record_id=rec.record_id,
                                retrieved_at=rec.retrieved_at,
                            )
                        )
                fields[name] = (
                    candidates[0]["value"] if candidates else selected.model_dump(mode="json")[name]
                )
                provenance[name] = candidates
                if len({dump(c["value"]) for c in candidates}) > 1:
                    conflicts.append(dict(field=name, values=[c["value"] for c in candidates]))
            metadata = MetadataSnapshot(
                edition_id=edition.edition_id,
                field_provenance=provenance,
                conflicts=conflicts,
                **fields,
            )
            edition.metadata_snapshot_id = metadata.snapshot_id
            if selected.kind != "unknown":
                edition.kind = selected.kind
            if edition.identity_status != "conflict":
                primary = any(e.namespace == "doi" for e in edition.external_ids) and any(
                    r.provider == "crossref" for r in records
                )
                primary |= any(
                    e.namespace == "arxiv" and e.version for e in edition.external_ids
                ) and any(r.provider == "arxiv" for r in records)
                edition.identity_status = (
                    "verified"
                    if primary
                    else "user_asserted"
                    if selected.provider == "user"
                    else "unresolved"
                )
            status_source = next(
                (r for r in records if r.publication_status in {"retracted", "withdrawn"}), selected
            )
            edition.publication_status = dict(
                status=status_source.publication_status,
                source=status_source.provider,
                observed_at=status_source.retrieved_at,
            )
            self.db.execute(
                "INSERT INTO metadata VALUES(?,?,?)",
                (metadata.snapshot_id, edition.edition_id, dump(metadata)),
            )
            self.db.execute(
                "UPDATE editions SET payload=? WHERE id=?", (dump(edition), edition.edition_id)
            )
            # Provider assertions about preprint/publication relations remain visible,
            # never transfer locators or claim judgments between these editions.
            for related in record.related_ids:
                for other in self.lookup(related):
                    self._relation(
                        edition.fabric_id,
                        other.fabric_id,
                        "is_version_of",
                        f"{record.provider}:{record.source_id}",
                    )
            # Indexed title-only suggestions avoid scanning the entire library.
            normalized = normalized_title(metadata.title)
            self.db.execute("DELETE FROM title_index WHERE edition_id=?", (edition.edition_id,))
            for row in self.db.execute(
                "SELECT edition_id FROM title_index WHERE title=?", (normalized,)
            ):
                other = self.edition(row[0])
                self._relation(
                    edition.fabric_id, other.fabric_id, "possible_duplicate", "normalized_title"
                )
            self.db.execute("INSERT INTO title_index VALUES(?,?)", (normalized, edition.edition_id))
            return edition

    def cache_get(self, key: str, stale: bool = False):
        row = self.db.execute("SELECT payload,expires FROM cache WHERE key=?", (key,)).fetchone()
        if row and (stale or row["expires"] > time.time()):
            return json.loads(row["payload"]), row["expires"] <= time.time()
        return None

    def cache_put(self, key: str, value, ttl: float):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO cache VALUES(?,?,?)", (key, dump(value), time.time() + ttl)
            )
            self.db.execute("DELETE FROM cache WHERE expires<?", (time.time() - 7 * 86400,))

    def acquire(self, key: str, interval: float, lease_seconds: float) -> tuple[str | None, float]:
        clock = time.time()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("INSERT OR IGNORE INTO runtime(key) VALUES(?)", (key,))
            row = self.db.execute("SELECT * FROM runtime WHERE key=?", (key,)).fetchone()
            wait = max(row["next_at"], row["lease_until"], row["circuit_until"]) - clock
            if wait > 0:
                return None, wait
            token = new_id()
            self.db.execute(
                "UPDATE runtime SET next_at=?,lease_until=?,token=? WHERE key=?",
                (clock + interval, clock + lease_seconds, token, key),
            )
            return token, 0

    def release(self, key: str, token: str, failure: bool = False, cooldown: float = 0):
        with self.db:
            row = self.db.execute(
                "SELECT failures FROM runtime WHERE key=? AND token=?", (key, token)
            ).fetchone()
            if not row:
                return
            failures = row[0] + 1 if failure else 0
            circuit = time.time() + 60 if failures >= 3 else 0
            self.db.execute(
                "UPDATE runtime SET lease_until=0,token=NULL,failures=?,circuit_until=?,next_at=max(next_at,?) WHERE key=?",
                (failures, circuit, time.time() + cooldown, key),
            )

    def blob_path(self, hash_value: str) -> Path:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", hash_value):
            raise FabricError("evidence_integrity_failed", "Invalid content hash.")
        return self.blobs / hash_value[7:]

    def write_blob(self, content: bytes) -> str:
        digest = sha(content)
        target = self.blob_path(digest)
        if target.exists():
            return digest
        used = sum(p.stat().st_size for p in self.blobs.iterdir() if p.is_file())
        if used + len(content) > self.cache_bytes:
            raise FabricError(
                "resource_limit",
                "Local content budget exceeded; increase cache_bytes or remove unneeded data explicitly.",
            )
        temp = target.with_suffix("." + new_id() + ".tmp")
        try:
            with temp.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        return digest

    def save_document(
        self, document: Document, event: RetrievalEvent, extraction: ExtractionSnapshot
    ):
        with self.db:
            self.db.execute(
                "INSERT INTO documents(id,edition_id,hash,touched,payload) VALUES(?,?,?,?,?)",
                (
                    document.document_id,
                    document.edition_id,
                    document.source_hash,
                    time.time(),
                    dump(document),
                ),
            )
            self.db.execute(
                "INSERT INTO retrievals VALUES(?,?,?)",
                (event.event_id, document.document_id, dump(event)),
            )
            self.db.execute(
                "INSERT INTO extractions VALUES(?,?,?)",
                (extraction.extraction_id, document.document_id, dump(extraction)),
            )
            for unit in extraction.text_units:
                start = 0
                while start < len(unit.text):
                    end = min(start + 1400, len(unit.text))
                    if end < len(unit.text):
                        boundary = unit.text.rfind(" ", start + 700, end)
                        if boundary > start:
                            end = boundary
                    if unit.text[start:end].strip():
                        pid = new_id()
                        text = unit.text[start:end]
                        self.db.execute(
                            "INSERT INTO passages VALUES(?,?,?,?,?,?,?)",
                            (
                                pid,
                                extraction.extraction_id,
                                document.edition_id,
                                unit.text_unit_id,
                                start,
                                end,
                                text,
                            ),
                        )
                        self.db.execute(
                            "INSERT INTO passages_fts(id,text) VALUES(?,?)", (pid, text)
                        )
                    if end == len(unit.text):
                        break
                    start = max(start + 1, end - 150)

    def documents(self, edition_id: str) -> list[Document]:
        return [
            Document.model_validate_json(r[0])
            for r in self.db.execute(
                "SELECT payload FROM documents WHERE edition_id=? ORDER BY touched DESC",
                (edition_id,),
            )
        ]

    def document(self, identifier: str) -> Document:
        return Document.model_validate(self._get("documents", identifier))

    def extraction(self, identifier: str) -> ExtractionSnapshot:
        return ExtractionSnapshot.model_validate(self._get("extractions", identifier))

    def retrieval(self, identifier: str) -> RetrievalEvent:
        return RetrievalEvent.model_validate(self._get("retrievals", identifier))

    def passage_search(
        self, edition_ids: list[str], query: str, limit: int = 48
    ) -> list[dict[str, Any]]:
        words = list(dict.fromkeys(re.findall(r"\w+", query.casefold())))[:64]
        stop = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "of",
            "to",
            "and",
            "in",
            "does",
            "do",
            "that",
            "with",
        }
        words = [w for w in words if w not in stop]
        if not words or not edition_ids:
            return []
        expression = " OR ".join('"' + word + '"' for word in words)
        placeholders = ",".join("?" for _ in edition_ids)
        rows = self.db.execute(
            f"SELECT p.*, bm25(passages_fts) AS score FROM passages_fts JOIN passages p ON p.id=passages_fts.id WHERE passages_fts MATCH ? AND p.edition_id IN ({placeholders}) ORDER BY score,p.id LIMIT ?",
            (expression, *edition_ids, limit),
        )
        return [dict(row) for row in rows]

    def save_evidence(self, evidence: EvidenceObject):
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO evidence VALUES(?,?,?,?)",
                (
                    evidence.evidence_id,
                    evidence.document_id,
                    evidence.extraction_id,
                    dump(evidence),
                ),
            )

    def evidence(self, identifier: str) -> EvidenceObject:
        try:
            evidence = EvidenceObject.model_validate(self._get("evidence", identifier))
            doc = self.document(evidence.document_id)
            ext = self.extraction(evidence.extraction_id)
            event = self.retrieval(evidence.retrieval_event_id)
            unit = next(
                u for u in ext.text_units if u.text_unit_id == evidence.locator.text_unit_id
            )
            raw = self.blob_path(doc.source_hash).read_bytes()
            valid = (
                sha(raw) == doc.source_hash == evidence.source_hash
                and ext.text_hash == evidence.text_hash
                and ext.document_id == doc.document_id == event.document_id
                and doc.edition_id == evidence.edition_id
                and self.edition(evidence.edition_id).fabric_id == evidence.fabric_id
                and unit.text[evidence.locator.char_start : evidence.locator.char_end]
                == evidence.excerpt
                and unit.page == evidence.locator.page
            )
            if not valid:
                raise ValueError("mismatch")
            return evidence
        except (ValueError, OSError, StopIteration) as exc:
            raise FabricError(
                "evidence_integrity_failed",
                "Stored evidence cannot be replayed against its document and extraction snapshot.",
            ) from exc

    def save_receipt(self, receipt: EvidenceReceipt):
        for identifier in receipt.evidence_ids:
            evidence = self.evidence(identifier)
            if evidence.edition_id != receipt.assessment.edition_id:
                raise FabricError(
                    "evidence_integrity_failed", "Receipt evidence belongs to a different edition."
                )
            if receipt.document_hashes.get(evidence.document_id) != evidence.source_hash:
                raise FabricError(
                    "evidence_integrity_failed",
                    "Receipt document hashes do not match the referenced evidence.",
                )
        with self.db:
            self.db.execute(
                "INSERT INTO receipts VALUES(?,?,?)",
                (receipt.receipt_id, receipt.assessment.edition_id, dump(receipt)),
            )
            for identifier in receipt.evidence_ids:
                self.db.execute(
                    "INSERT INTO receipt_evidence VALUES(?,?)", (receipt.receipt_id, identifier)
                )
            for document_id in receipt.document_hashes:
                self.db.execute("UPDATE documents SET pinned=1 WHERE id=?", (document_id,))

    def receipt(self, identifier: str) -> EvidenceReceipt:
        return EvidenceReceipt.model_validate(self._get("receipts", identifier))
