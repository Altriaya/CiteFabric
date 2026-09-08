# Changelog

## Unreleased

- Add opt-in `structured_v3` retrieval: versioned text-region indexes, literal/reference matching, scope and cost context, compact spans and explicit table-reference dependencies. Default remains v2.
- Add atomic schema 1→2 migration with a consistent pre-upgrade backup; derived index failures fall back explicitly to v2.
- Add retrieval traces and per-extraction evidence bundles with unassessed lexical roles; source slices and historical receipts remain immutable.
- Compare v2/v3 on 38 real-paper cases at 6000/12000 characters and add 39 synthetic regression tests for conditions, scope, budgets, references, migration, cancellation and boundaries.

- Add auditable Chinese research-glossary expansion, lexical concept reranking and metric aliases; no semantic translation backend.
- Expand and coalesce same-page evidence within the requested character budget, preserving immutable source slices and receipts; expose PDF quality hints and seed-score provenance.
- Add `expand_query` and `include_context` controls to SDK, CLI and MCP, enabled by default.
- Return the existing extraction ID and coverage on repeated document imports.
- Extend local regression experiments to six papers and 38 bilingual cases, with ablations and SDK/MCP parity checks including empty results.

## 0.1.0 — local implementation, not published

- Four-source discovery with explicit failures, bounded retry, shared provider leases and cached observation timestamps.
- Stable local paper/edition IDs, conservative identifier deduplication, quarantined conflicts and immutable metadata snapshots.
- Local PDF/text import, controlled OA PDF retrieval, killable text extraction, FTS5 passage retrieval and hash-based evidence replay.
- Claim/evidence audit receipts with semantic verdict `unavailable`; no model backend is included.
- BibTeX and CSL-JSON export with a separate provenance manifest.
- Python SDK, CLI, five stdio MCP tools and bounded resource reads.
- Generated schemas, offline regression tests, source/wheel packaging and a cross-platform CI configuration.
