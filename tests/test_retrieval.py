import pytest

from citefabric import CiteFabricClient
from citefabric.retrieval import quality_flags, query_plan

from .conftest import pdf_bytes


async def test_context_never_crosses_pdf_pages_or_documents(config, tmp_path):
    from io import BytesIO

    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for content in ("TargetMetric 42 percent.", "UnrelatedPage 99 percent."):
        writer.add_page(PdfReader(BytesIO(pdf_bytes(content))).pages[0])
    path = tmp_path / "two-pages.pdf"
    writer.write(path)
    other = tmp_path / "other.txt"
    other.write_text("TargetMetric in another document: 3 percent.")
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        await client.import_document(other)
        result = await client.find_evidence(
            [{"ref": imported.data["fabric_id"]}], "TargetMetric", max_chars=12000
        )
        assert result.data["hits"]
        for hit in result.data["hits"]:
            evidence = hit["evidence"]
            assert evidence["locator"]["page"] == 1
            assert "UnrelatedPage" not in evidence["excerpt"]
            assert "another document" not in evidence["excerpt"]
            assert hit["seed_passage_ids"]
            assert client.store.evidence(evidence["evidence_id"]).excerpt == evidence["excerpt"]


async def test_chinese_research_intent_is_not_only_a_model_name(config, tmp_path):
    path = tmp_path / "study.txt"
    path.write_text(
        "Model baseline architecture. " * 100
        + "\nTraining cost and inference overhead: training takes 42 hours. " * 50
    )
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        selectors = [{"ref": imported.data["fabric_id"]}]
        result = await client.find_evidence(
            selectors, "模型的训练开销是多少？", include_context=False
        )
        assert result.status == "ok"
        assert "Training cost" in result.data["hits"][0]["evidence"]["excerpt"]
        plan = result.data["query_plan"]
        assert plan["original"] == "模型的训练开销是多少？"
        assert plan["semantic_translation"] is False
        assert any(m["source"] == "开销" for m in plan["mappings"])
        assert result.warnings


async def test_page_expansion_preserves_original_evidence_and_receipt(config, tmp_path):
    path = tmp_path / "table.pdf"
    text = (
        "Table 1: Method Accuracy Units. "
        + "background context " * 90
        + "UniqueTarget 97.8 percent."
    )
    path.write_bytes(pdf_bytes(text))
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        selectors = [{"ref": imported.data["fabric_id"]}]
        found = await client.find_evidence(selectors, "UniqueTarget", include_context=False)
        old = found.data["hits"][0]["evidence"]
        assert "Table 1" not in old["excerpt"]
        receipt = (
            await client.verify_claim(
                "Accuracy is 97.8%", selectors, evidence_ids=[old["evidence_id"]]
            )
        ).data["receipts"][0]
        expanded = await client.find_evidence(selectors, "UniqueTarget", max_chars=6000)
        evidence = expanded.data["hits"][0]["evidence"]
        assert "Table 1" in evidence["excerpt"] and "UniqueTarget" in evidence["excerpt"]
        assert evidence["evidence_id"] != old["evidence_id"]
        assert evidence["locator"]["page"] == old["locator"]["page"] == 1
        assert evidence["source_hash"] == old["source_hash"]
        assert evidence["edition_id"] == old["edition_id"]
        assert client.store.evidence(old["evidence_id"]).model_dump(mode="json") == old
        assert client.store.receipt(receipt["receipt_id"]).model_dump(mode="json") == receipt
        assert client.store.evidence(evidence["evidence_id"]).excerpt == text
        repeated = await client.find_evidence(selectors, "UniqueTarget", max_chars=6000)
        assert repeated.data["hits"][0]["evidence"] == evidence


@pytest.mark.parametrize("budget", [500, 1600, 3000, 6000, 12000])
async def test_context_obeys_budget_and_does_not_mutate_offsets(config, tmp_path, budget):
    path = tmp_path / "long.txt"
    path.write_text("Context with emoji 🧬 evidence metric. " * 300, encoding="utf-8", newline="\n")
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        found = await client.find_evidence(
            [{"ref": imported.data["fabric_id"]}],
            "evidence metric",
            max_chars=budget,
            max_passages=3,
        )
        hits = found.data["hits"]
        assert len(hits) <= 3
        assert sum(len(h["evidence"]["excerpt"]) for h in hits) <= budget
        for hit in hits:
            evidence = client.store.evidence(hit["evidence"]["evidence_id"])
            assert len(evidence.excerpt) == evidence.locator.char_end - evidence.locator.char_start


def test_query_normalization_and_quality_are_explicit_and_nonsemantic():
    plan = query_plan("MAE_A 误差是多少？")
    assert "MAEA" in plan["metric_aliases"]
    assert not query_plan("完全未覆盖的中文词", enabled=False)["mappings"]
    assert "suspicious_pdf_glyphs" in quality_flags("/uni00000014")
    assert "scientific_symbol_encoding_uncertain" in quality_flags("36þ5")
    assert "possibly_joined_numeric_cells" in quality_flags("20.105.14")
    assert "bibliography_like" in quality_flags("[1] A\n[2] B\n[3] C")
