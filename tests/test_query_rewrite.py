from citefabric import CiteFabricClient
from citefabric.query_rewrite import QueryRewrite


async def test_faithful_rewrite_is_applied_and_audited(config, tmp_path):
    path = tmp_path / "study.txt"
    path.write_text("The ModelX training cost was 42 hours.")

    async def rewrite(query):
        assert query == "ModelX 的训练开销是多少？"
        return QueryRewrite(
            query="What was the training cost of ModelX?", model="test-model", prompt_version="p1"
        )

    async with CiteFabricClient(config, query_rewriter=rewrite) as client:
        imported = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": imported.data["fabric_id"]}],
            "ModelX 的训练开销是多少？",
            include_context=False,
            query_rewrite="english_faithful",
        )

    assert result.status == "ok"
    assert result.data["query_rewrite"]["status"] == "applied"
    assert result.data["query_rewrite"]["model"] == "test-model"
    assert result.data["query_plan"]["original"] == "ModelX 的训练开销是多少？"
    assert result.data["query_plan"]["effective_query"] == "What was the training cost of ModelX?"
    assert "42 hours" in result.data["hits"][0]["evidence"]["excerpt"]


async def test_rewrite_missing_protected_literal_falls_back(config, tmp_path):
    path = tmp_path / "study.txt"
    path.write_text("Accuracy was 98 percent.")

    async def rewrite(_query):
        return QueryRewrite(query="What was the accuracy?", model="test-model", prompt_version="p1")

    async with CiteFabricClient(config, query_rewriter=rewrite) as client:
        imported = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": imported.data["fabric_id"]}],
            "准确率是98%吗？",
            include_context=False,
            query_rewrite="english_faithful",
        )

    rewrite_data = result.data["query_rewrite"]
    assert rewrite_data["status"] == "rejected"
    assert "protected_literal_missing:98%" in rewrite_data["validation"]["rejection_reasons"]
    assert result.data["query_plan"]["effective_query"] == "准确率是98%吗？"


async def test_rewrite_accepts_equivalent_percentage_spacing(config, tmp_path):
    path = tmp_path / "study.txt"
    path.write_text("Accuracy was 98 percent.")

    async def rewrite(_query):
        return QueryRewrite(query="Was accuracy 98 %?", model="test-model", prompt_version="p1")

    async with CiteFabricClient(config, query_rewriter=rewrite) as client:
        imported = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": imported.data["fabric_id"]}],
            "准确率是98%吗？",
            include_context=False,
            query_rewrite="english_faithful",
        )

    assert result.data["query_rewrite"]["status"] == "applied"


async def test_rewrite_without_approved_backend_falls_back(config, tmp_path):
    path = tmp_path / "study.txt"
    path.write_text("Training cost was 42 hours.")
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": imported.data["fabric_id"]}],
            "训练开销是多少？",
            include_context=False,
            query_rewrite="english_faithful",
        )

    assert result.data["query_rewrite"]["status"] == "not_configured"
    assert result.data["query_plan"]["effective_query"] == "训练开销是多少？"
    assert result.warnings
