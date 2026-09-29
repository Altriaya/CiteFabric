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


def test_offline_structured_v6_routes_only_explicit_material_queries():
    ordinary = offline_structured_plan(
        "BERT uses masked language modeling", material_channels=True, safe_material_routing=True
    )
    material = offline_structured_plan(
        "表 3 中 17.607 与 39.303 分别是多少？",
        material_channels=True,
        safe_material_routing=True,
    )

    assert ordinary["method"] == "offline-safe-material-route-v6"
    assert ordinary["material_signal"] is False
    assert ordinary["front_matter_tiebreak"] is False
    assert material["material_signal"] is True
    assert material["joint_requested"] is True
    assert material["front_matter_tiebreak"] is False


def test_offline_structured_v6_does_not_route_on_a_year_alone():
    year = offline_structured_plan(
        "How stable was the ring during 2017?",
        material_channels=True,
        safe_material_routing=True,
    )
    quantitative = offline_structured_plan(
        "As of March 28 2016 about",
        material_channels=True,
        safe_material_routing=True,
    )

    assert year["numeric_terms"] == ["2017"]
    assert year["quantitative_terms"] == []
    assert year["material_signal"] is False
    assert quantitative["quantitative_terms"] == ["28"]
    assert quantitative["material_signal"] is True


async def test_offline_structured_v6_preserves_v2_for_ordinary_queries(config, tmp_path):
    path = tmp_path / "ordinary.txt"
    path.write_text(
        "Early general background.\n\n"
        "The masked language modeling objective predicts hidden tokens.\n\n"
        "Later unrelated discussion."
    )
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        selector = [{"ref": imported.data["fabric_id"]}]
        baseline = await client.find_evidence(
            selector, "masked language modeling objective", retrieval_policy="v2"
        )
        candidate = await client.find_evidence(
            selector,
            "masked language modeling objective",
            retrieval_policy="offline_structured_v6",
        )

    assert candidate.data["query_plan"]["route"] == "v2_baseline"
    assert candidate.data["rerank_method"] == "v2-baseline-invariant"
    assert [h["evidence"]["excerpt"] for h in candidate.data["hits"]] == [
        h["evidence"]["excerpt"] for h in baseline.data["hits"]
    ]


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


@pytest.mark.parametrize(
    "policy", ["v2", "offline_structured_v4", "offline_structured_v5", "offline_structured_v6"]
)
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
