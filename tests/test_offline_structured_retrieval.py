import pytest

from citefabric import CiteFabricClient
from citefabric.retrieval import offline_structured_plan


def test_offline_structured_plan_keeps_language_channels_separate():
    plan = offline_structured_plan("BACKTIME 在所有条件下是否保证没有虚警率上界？")

    glossary = next(
        channel for channel in plan["channels"] if channel["id"] == "bilingual_glossary"
    )
    assert "false" in glossary["query"] and "upper" in glossary["query"]
    assert not any("\u3400" <= char <= "\u9fff" for char in glossary["query"])
    assert any(channel["id"] == "entity:BACKTIME" for channel in plan["channels"])
    assert any(channel["id"] == "scope_context" for channel in plan["channels"])


def test_offline_structured_plan_does_not_infer_a_table_from_a_numeric_question():
    plan = offline_structured_plan("评估了多少种已有防御？")

    assert not plan["table_requested"]
    assert not any(channel["id"] == "table_context" for channel in plan["channels"])


def test_offline_structured_v5_adds_material_channels_without_changing_v4():
    query = "表 3 中 17.607 和 39.303 的训练损失是否来自交集样本？"
    v4 = offline_structured_plan(query)
    v5 = offline_structured_plan(query, material_channels=True)

    assert not v4["material_channels"]
    assert not any(channel["id"] == "numeric_bundle" for channel in v4["channels"])
    assert not any(channel["id"].startswith("reference:") for channel in v4["channels"])
    assert "union" not in v4["expanded"]

    assert v5["method"] == "offline-material-channels-v5"
    assert v5["numeric_terms"] == ["17.607", "39.303"]
    assert v5["reference_terms"] == [{"kind": "table", "number": "3"}]
    assert any(channel["id"] == "numeric_bundle" for channel in v5["channels"])
    assert any(channel["id"] == "reference:table:3" for channel in v5["channels"])
    assert "intersection" in v5["expanded"] and "union" in v5["expanded"]


def test_offline_structured_v5_expands_small_number_words():
    plan = offline_structured_plan("评估了 13 种防御", material_channels=True)
    numeric = next(channel for channel in plan["channels"] if channel["id"] == "numeric_bundle")

    assert plan["numeric_aliases"] == {"13": ["thirteen"]}
    assert numeric["query"] == "13 thirteen"


async def test_offline_structured_v4_uses_glossary_without_combining_chinese_fts(config, tmp_path):
    path = tmp_path / "study.txt"
    path.write_text(
        "ModelRiver experimental details.\n\n"
        "Training cost and inference overhead: training takes 42 hours.\n\n"
        "Limitations: these tests are consistent with the observed setting only."
    )
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": imported.data["fabric_id"]}],
            "ModelRiver 的训练开销是多少，是否保证所有条件？",
            retrieval_policy="offline_structured_v4",
            include_context=False,
        )

    assert result.status == "ok"
    assert result.data["retrieval_version"] == "4"
    assert result.data["rerank_method"] == "bounded_channel_rrf-v1"
    assert any("42 hours" in hit["evidence"]["excerpt"] for hit in result.data["hits"])
    trace = result.data["query_plan"]["channel_trace"]
    assert {item["id"] for item in trace} >= {"original", "bilingual_glossary", "scope_context"}
    glossary = next(item for item in trace if item["id"] == "bilingual_glossary")
    assert glossary["candidates"] >= 1


@pytest.mark.parametrize("policy", ["v2", "offline_structured_v4", "offline_structured_v5"])
async def test_offline_structured_policy_preserves_bounded_evidence(config, tmp_path, policy):
    path = tmp_path / "bounded.txt"
    path.write_text("Table 1: ModelRiver accuracy 97.8 percent. " + "context " * 200)
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": imported.data["fabric_id"]}],
            "ModelRiver 表格准确率是多少？",
            retrieval_policy=policy,
            max_chars=700,
        )

    assert sum(len(hit["evidence"]["excerpt"]) for hit in result.data["hits"]) <= 700
