"""Replay the supplied-paper evidence benchmark without a semantic verifier.

Run: uv run python scripts/validate_real_papers.py
The PDF bibliography is a reviewed local fixture, explicitly user_asserted.
Gold labels/anchors are used only for reporting, never passed to retrieval.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from citefabric import CiteFabricClient, Config
from citefabric.models import Author, ExternalID, Issued, Result, SourceRecord


def write_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def run(args):
    fixture = json.loads(args.cases.read_text(encoding="utf-8"))
    # Validate every input before opening the workspace or writing run artifacts.
    for paper in fixture["papers"]:
        raw = (args.input_dir / paper["filename"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != paper["sha256"]:
            raise ValueError(f"Source hash changed: {paper['key']}; review the cases first.")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    config = Config(data_dir=args.data_dir, offline=True, parse_timeout=60)
    manifest = {
        "started_at": datetime.now(UTC).isoformat(),
        "mode": "local_pdf_with_locally_transcribed_bibliography",
        "semantic_verifier": "not_configured",
        "cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "query_language": args.query_language,
        "source_code_hashes": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path("src/citefabric").glob("*.py"))
        },
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("citefabric", "pypdf")},
        "data_dir": str(args.data_dir.resolve()),
        "retrieval": {
            "max_passages": 6,
            "max_chars": args.max_chars,
            "allow_abstract": False,
            "retrieval_policy": args.retrieval_policy,
        },
        "papers": {},
    }
    write_json(args.output_dir / "cases.json", fixture)
    for name in ("expand_query", "include_context"):
        value = getattr(args, name)
        if value is not None:
            manifest["retrieval"][name] = value
    results = []
    all_receipts = []
    all_selectors = []
    replayed = set()
    async with CiteFabricClient(config) as client:
        doctor = await client.doctor()
        write_json(args.output_dir / "doctor.json", doctor.model_dump(mode="json"))
        for paper in fixture["papers"]:
            # Metadata is transcribed from the provided PDF, not claimed to be an API result.
            record = SourceRecord(
                provider="user",
                source_id="supplied-pdf:" + paper["sha256"],
                source_uri="local-import:" + paper["filename"],
                title=paper["title"],
                authors=[Author(display_name=name) for name in paper["authors"]],
                issued=Issued(year=paper["year"]),
                kind=paper.get("kind", "preprint"),
                version=paper["version"],
                external_ids=[
                    ExternalID(namespace="arxiv", value=paper["arxiv"], version=paper["version"])
                    if paper.get("arxiv")
                    else ExternalID(namespace="doi", value=paper["doi"])
                ],
            )
            edition = client.store.ingest(record)
            imported = await client.import_document(
                args.input_dir / paper["filename"], edition_id=edition.edition_id
            )
            write_json(
                args.output_dir / f"{paper['key']}_import.json", imported.model_dump(mode="json")
            )
            if imported.status not in {"ok", "partial"} or not imported.data:
                raise RuntimeError(imported.model_dump_json())
            extraction_id = imported.data["extraction_id"]
            if extraction_id is None:  # Compatibility with 0.1's cached-import response.
                row = client.store.db.execute(
                    "SELECT id FROM extractions WHERE document_id=? ORDER BY rowid DESC LIMIT 1",
                    (imported.data["document"]["document_id"],),
                ).fetchone()
                if row is None:
                    raise RuntimeError("Imported document has no extraction snapshot.")
                extraction_id = row[0]
            extraction = client.store.extraction(extraction_id)
            write_json(
                args.output_dir / f"{paper['key']}_extraction.json",
                extraction.model_dump(mode="json"),
            )
            selector = {"ref": edition.fabric_id, "edition_id": edition.edition_id}
            all_selectors.append(selector)
            manifest["papers"][paper["key"]] = {
                "selector": selector,
                "identity_status": edition.identity_status,
                "document": imported.data["document"],
                "coverage": extraction.coverage.model_dump(mode="json"),
            }
            print(f"Imported {paper['key']}: {imported.status}, {extraction.coverage}", flush=True)
        write_json(args.output_dir / "manifest.json", manifest)

        for case in fixture["cases"]:
            selector = manifest["papers"][case["paper"]]["selector"]
            query = (
                case["retrieval_query_en"] if args.query_language == "en" else case["question_zh"]
            )
            found = await client.find_evidence([selector], query, **manifest["retrieval"])
            hits = (found.data or {}).get("hits", [])
            ids = []
            for hit in hits:
                evidence_id = hit["evidence"]["evidence_id"]
                # Replays source hash, text hash, offsets, excerpt and edition binding.
                checked = client.store.evidence(evidence_id)
                assert checked.model_dump(mode="json") == hit["evidence"]
                ids.append(evidence_id)
                replayed.add(evidence_id)
            verification = (
                await client.verify_claim(case["claim_zh"], [selector], evidence_ids=ids)
                if ids
                else Result(
                    status="no_results",
                    data={"receipts": []},
                    warnings=["Verification not invoked: no retrieved evidence."],
                )
            )
            receipts = (verification.data or {}).get("receipts", [])
            all_receipts.extend(r["receipt_id"] for r in receipts)
            page_text = {}
            for hit in hits:
                evidence = hit["evidence"]
                page_text.setdefault(evidence["locator"]["page"], []).append(evidence["excerpt"])
            gold_checks = []
            for gold in case["gold"]:
                excerpts = page_text.get(gold["page"], [])
                gold_checks.append(
                    {
                        "page": gold["page"],
                        "page_hit": bool(excerpts),
                        "anchors": [
                            {"text": a, "hit": any(a in excerpt for excerpt in excerpts)}
                            for a in gold["anchors"]
                        ],
                    }
                )
            item = {
                "case_id": case["id"],
                "query": query,
                "retrieval": found.model_dump(mode="json"),
                "verification": verification.model_dump(mode="json"),
                "integrity_replayed": len(ids),
                "gold_checks": gold_checks,
                "gold_page_hit": all(g["page_hit"] for g in gold_checks) if gold_checks else None,
                "gold_anchor_hit": all(a["hit"] for g in gold_checks for a in g["anchors"])
                if gold_checks
                else None,
                "manual_assessment": None,
            }
            results.append(item)
            write_json(args.output_dir / f"{case['id']}.json", item)
            print(
                f"{case['id']}: {found.status}, pages={list(page_text)}, "
                f"gold_page={item['gold_page_hit']}, gold_anchors={item['gold_anchor_hit']}",
                flush=True,
            )

        for fmt, suffix in [("bibtex", "bib"), ("csl_json", "csl.json")]:
            exported = await client.export_citations(all_selectors, fmt, receipt_ids=all_receipts)
            write_json(args.output_dir / f"export_{fmt}.json", exported.model_dump(mode="json"))
            if exported.status != "ok" or not exported.data:
                raise RuntimeError(exported.model_dump_json())
            content = exported.data["content"]
            path = args.output_dir / f"citations.{suffix}"
            if isinstance(content, str):
                path.write_text(content, encoding="utf-8")
            else:
                write_json(path, content)

    scored = [r for r in results if r["gold_page_hit"] is not None]
    summary = {
        "cases": len(results),
        "annotation_distribution": dict(Counter(c["expected_verdict"] for c in fixture["cases"])),
        "retrieval_status": dict(Counter(r["retrieval"]["status"] for r in results)),
        "gold_page_hits": sum(r["gold_page_hit"] for r in scored),
        "gold_anchor_hits": sum(r["gold_anchor_hit"] for r in scored),
        "gold_scored_cases": len(scored),
        "evidence_occurrences_replayed": sum(r["integrity_replayed"] for r in results),
        "unique_evidence_replayed": len(replayed),
        "receipts": len(all_receipts),
        "semantic_accuracy": None,
        "query_language": args.query_language,
        "limitations": [
            "Gold page and anchor hits are mechanical coverage checks, not semantic accuracy.",
            "All semantic labels are source-review annotations; the automatic verifier is unavailable.",
            "English queries and Chinese questions are manually prepared before retrieval.",
            "Candidate selection and context budgets may return fewer than max_passages; v2 keeps its per-edition seed cap.",
            "This small, non-blinded regression set is not an independent benchmark.",
        ],
    }
    write_json(args.output_dir / "results.json", results)
    write_json(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Artifacts: {args.output_dir.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("benchmarks/real_papers.json"))
    parser.add_argument("--input-dir", type=Path, default=Path("data_test"))
    parser.add_argument("--query-language", choices=["en", "zh"], default="en")
    parser.add_argument("--retrieval-policy", choices=["v2", "structured_v3"], default="v2")
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--expand-query", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--include-context", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--data-dir", type=Path, default=Path(".citefabric/real_papers"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/validation/real_papers")
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
    )
    asyncio.run(run(parser.parse_args()))
