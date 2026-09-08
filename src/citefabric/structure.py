"""Rebuildable text-region index. Regions are not verified table cells or layout."""

from __future__ import annotations

import asyncio
import json
import re
from uuid import NAMESPACE_URL, uuid5

from .models import ExtractionSnapshot, FabricError
from .retrieval import searchable_text
from .storage import Store, dump

BUILDER_VERSION = "text-regions-v2"
MAX_TEXT_CHARS = 3_000_000
MAX_BLOCKS = 6000
TABLE = re.compile(r"(?m)^\s*(?:Table\s+\d+|TABLE\s+[IVX]+)[.:\s]")
SCOPE = re.compile(
    r"(?im)^\s*(?:(?:[IVX]+|\d+(?:\.\d+)*)[. ]+)?"
    r"(limitations?(?: and future work)?|future work|discussion)\b[^\n]{0,70}"
)


def stable_id(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, "citefabric:" + value))


def windows(text: str, start: int, end: int, size: int = 1100):
    """Keep raw offsets and prefer paragraph/sentence ends; no normalized slicing."""
    while start < end:
        right = min(start + size, end)
        if right < end:
            boundaries = list(
                re.finditer(r"\n\s*\n|[.!?][ \t]*\n", text[start + size // 2 : right])
            )
            if boundaries:
                right = start + size // 2 + boundaries[-1].end()
            else:
                newline = text.rfind("\n", start + size // 2, right)
                if newline > start:
                    right = newline + 1
        yield start, right
        if right == end:
            break
        start = max(start + 1, right - 180)


def regions(text: str) -> list[tuple[str, int, int]]:
    result = [("page", 0, len(text))] if text.strip() else []
    result.extend(("paragraph", a, b) for a, b in windows(text, 0, len(text)))
    tables = list(TABLE.finditer(text))
    for i, match in enumerate(tables):
        stop = tables[i + 1].start() if i + 1 < len(tables) else len(text)
        stop = min(stop, match.start() + 7000)
        last_row = None
        gap = 0
        for line in re.finditer(r"[^\n]*(?:\n|$)", text[match.end() : stop]):
            content = line.group()
            numbers = re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", content)
            row_like = (
                len(numbers) >= 3
                and len(re.findall(r"[A-Za-z]", content)) < 100
                and sum(len(n) for n in numbers) / max(1, len(content)) > 0.2
            )
            if row_like:
                last_row = match.end() + line.end()
                gap = 0
            elif last_row:
                gap += 1
                if gap >= 3:
                    break
        if last_row:
            result.append(("table", match.start(), last_row))
        else:
            result.append(("table_ambiguous", match.start(), min(stop, match.start() + 1600)))
    for match in re.finditer(r"(?im)^\s*(?:fig(?:ure)?\.?\s*\d+)\s*[.|:]", text):
        result.append(("figure", match.start(), min(len(text), match.start() + 2200)))
    headings = list(SCOPE.finditer(text))
    for i, match in enumerate(headings):
        kind = "future" if match.group(1).casefold().startswith("future") else "scope"
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        result.extend((kind, a, b) for a, b in windows(text, match.start(), end, 1800))
    # Local qualifiers outside explicitly named sections remain unverified candidates.
    cues = re.finditer(
        r"no evidence (?:for|of)|all (?:three|these) tests|only an upper bound|"
        r"confidence intervals?|credible intervals?|averaged across|"
        r"no inference[-\s]+time overhead|training (?:time|cost)|precision[–-]recall",
        searchable_text(text),
    )
    # Normalization can change string length: locate candidates by scoring raw windows,
    # never by reusing a normalized match offset.
    if next(cues, None):
        for a, b in windows(text, 0, len(text), 1600):
            normalized = searchable_text(text[a:b])
            if re.search(
                r"no evidence|tests are consistent|upper bound|interval|overhead|training time|training cost|precision[–-]recall",
                normalized,
            ):
                result.append(("qualifier", a, b))
    return list(dict.fromkeys(result))


async def ensure_index(store: Store, extraction: ExtractionSnapshot, edition_id: str) -> str:
    identifier = stable_id(f"{BUILDER_VERSION}:{extraction.extraction_id}:{extraction.text_hash}")
    if store.db.execute("SELECT 1 FROM structure_indexes WHERE id=?", (identifier,)).fetchone():
        retire_old_search_rows(store, identifier, extraction.extraction_id)
        return identifier
    if len(extraction.text_snapshot) > MAX_TEXT_CHARS or len(extraction.text_units) > 300:
        raise FabricError(
            "structure_index_limit", "Structure indexing exceeds the bounded text limit."
        )
    blocks = []
    for unit in extraction.text_units:
        for kind, start, end in regions(unit.text):
            if not unit.text[start:end].strip():
                continue
            bid = stable_id(f"{identifier}:{unit.text_unit_id}:{kind}:{start}:{end}")
            blocks.append(
                (
                    bid,
                    identifier,
                    extraction.extraction_id,
                    edition_id,
                    unit.text_unit_id,
                    start,
                    end,
                    kind,
                    unit.text[start:end],
                )
            )
        if len(blocks) > MAX_BLOCKS:
            raise FabricError("structure_index_limit", "Too many derived text blocks.")
        await asyncio.sleep(0)
    manifest = {
        "builder_version": BUILDER_VERSION,
        "text_hash": extraction.text_hash,
        "status": "ready",
        "units": len(extraction.text_units),
        "blocks": len(blocks),
        "table_cells_verified": False,
    }
    # Compute outside a transaction, publish all blocks atomically; concurrent builders reuse.
    with store.db:
        inserted = store.db.execute(
            "INSERT OR IGNORE INTO structure_indexes VALUES(?,?,?)",
            (identifier, extraction.extraction_id, dump(manifest)),
        )
        if inserted.rowcount:
            store.db.executemany("INSERT INTO structure_blocks VALUES(?,?,?,?,?,?,?,?,?)", blocks)
            store.db.executemany(
                "INSERT INTO structure_fts VALUES(?,?)",
                [(b[0], searchable_text(b[-1])) for b in blocks],
            )
    retire_old_search_rows(store, identifier, extraction.extraction_id)
    return identifier


def retire_old_search_rows(store: Store, identifier: str, extraction_id: str) -> None:
    """Historical derived blocks stay auditable but do not duplicate BM25 statistics."""
    with store.db:
        store.db.execute(
            "DELETE FROM structure_fts WHERE id IN (SELECT id FROM structure_blocks WHERE extraction_id=? AND index_id<>?)",
            (extraction_id, identifier),
        )


def read_manifest(store: Store, identifier: str) -> dict:
    return json.loads(
        store.db.execute(
            "SELECT payload FROM structure_indexes WHERE id=?", (identifier,)
        ).fetchone()[0]
    )
