import json

import pytest

from citefabric import CiteFabricClient
from citefabric.models import FabricError

from .conftest import pdf_bytes, record


async def test_end_to_end_receipt_export_and_replay(config, tmp_path):
    path = tmp_path / "source.txt"
    path.write_text(
        "研究 🧠\nMemory improved completion on Task A. No other benchmark was evaluated.",
        encoding="utf-8",
    )
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        assert imported.status == "ok"
        selector = [{"ref": imported.data["fabric_id"], "edition_id": imported.data["edition_id"]}]
        result = await client.find_evidence(selector, "memory benchmark")
        assert result.status == "ok"
        evidence = result.data["hits"][0]["evidence"]
        assert evidence["locator"]["page"] is None
        assert "🧠" in evidence["excerpt"]
        verified = await client.verify_claim(
            "Memory improves all benchmarks.", selector, evidence_ids=[evidence["evidence_id"]]
        )
        assert verified.status == "partial"
        receipt = verified.data["receipts"][0]
        assert receipt["assessment"]["verdict"] == "unavailable"
        assert receipt["grounding_status"] == "verified"
        exported = await client.export_citations(
            selector, "csl_json", receipt_ids=[receipt["receipt_id"]]
        )
        assert exported.status == "ok"
        assert (
            exported.data["provenance_manifest"][0]["claim_verdicts"][0]["verdict"] == "unavailable"
        )
        client.store.blob_path(evidence["source_hash"]).write_bytes(b"tampered")
        with pytest.raises(FabricError, match="replayed"):
            client.store.evidence(evidence["evidence_id"])
        read = await client.read_resource("citefabric://receipts/" + receipt["receipt_id"])
        assert read.data["availability"] == "source_unavailable"
        bad_export = await client.export_citations(
            selector, "bibtex", receipt_ids=[receipt["receipt_id"]]
        )
        assert bad_export.status == "failed"


async def test_pdf_page_locator_and_scan_abstention(config, tmp_path):
    path = tmp_path / "article.pdf"
    path.write_bytes(pdf_bytes("Memory improved completion on Task A."))
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        assert imported.status == "ok", imported
        result = await client.find_evidence(
            [{"ref": imported.data["fabric_id"]}], "Memory completion"
        )
        assert result.data["hits"][0]["evidence"]["locator"]["page"] == 1
        path.write_bytes(pdf_bytes())
        scan = await client.import_document(path)
        assert scan.status == "failed" and scan.errors[0].code == "ocr_required"


async def test_missing_paper_preserves_other_evidence(config, tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("Memory benchmark evidence.")
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": imported.data["fabric_id"]}, {"ref": "doi:10.1234/missing"}], "memory"
        )
        assert result.status == "partial" and len(result.data["hits"]) == 1


async def test_receipt_rejects_another_editions_evidence(config, tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("Memory benchmark evidence.")
    async with CiteFabricClient(config) as client:
        a = await client.import_document(path)
        b = client.store.ingest(record())
        found = await client.find_evidence([{"ref": a.data["fabric_id"]}], "memory")
        invalid = await client.verify_claim(
            "Memory helps",
            [{"ref": b.fabric_id}],
            evidence_ids=[found.data["hits"][0]["evidence"]["evidence_id"]],
        )
        assert invalid.errors[0].code == "invalid_argument"


async def test_citation_uses_historical_metadata_snapshot(config, tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("Memory benchmark evidence.")
    async with CiteFabricClient(config) as client:
        edition = client.store.ingest(record())
        await client.import_document(path, edition.edition_id)
        selectors = [{"ref": edition.fabric_id}]
        receipt = (await client.verify_claim("Memory helps", selectors)).data["receipts"][0]
        updated = client.store.ingest(
            record(title="Memory improves task completion: revised title")
        )
        assert updated.metadata_snapshot_id != edition.metadata_snapshot_id
        output = await client.export_citations(
            selectors, "csl_json", receipt_ids=[receipt["receipt_id"]]
        )
        assert output.data["content"][0]["title"] == "Memory improves task completion"


async def test_budget_never_truncates_existing_evidence(config, tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("memory performance " * 200)
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": imported.data["fabric_id"]}], "memory", max_chars=500
        )
        assert sum(len(h["evidence"]["excerpt"]) for h in result.data["hits"]) <= 500
        assert result.meta.truncated


async def test_unsupported_formats_are_explicit(config):
    async with CiteFabricClient(config) as client:
        result = await client.export_citations([{"ref": "doi:10.1234/example"}], "apa")
        assert result.errors[0].code == "unsupported_format"


async def test_reimport_identical_file_is_idempotent(config, tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("Memory benchmark evidence.")
    async with CiteFabricClient(config) as client:
        first = await client.import_document(source)
        second = await client.import_document(source)
        assert first.data["fabric_id"] == second.data["fabric_id"]
        assert first.data["document"]["document_id"] == second.data["document"]["document_id"]
        assert first.data["extraction_id"] == second.data["extraction_id"]
        assert first.data["extraction_id"] is not None


def test_design_fixture_matches_domain_models():
    from pathlib import Path

    from citefabric.models import Document, EvidenceObject, EvidenceReceipt, ExtractionSnapshot

    bundle = json.loads(Path("docs/examples/evidence-bundle.json").read_text())
    Document.model_validate(bundle["document"])
    ExtractionSnapshot.model_validate(bundle["extraction_snapshot"])
    EvidenceObject.model_validate(bundle["evidence"][0])
    EvidenceReceipt.model_validate(bundle["receipt"])
