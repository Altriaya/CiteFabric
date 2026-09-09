"""Synthetic condition/qualifier cases; not a paper-quality or semantic benchmark."""

import asyncio
import itertools
import sqlite3

import pytest

from citefabric import CiteFabricClient
from citefabric.evidence_selection import entity_matches, plan_query
from citefabric.models import FabricError
from citefabric.storage import Store
from citefabric.structure import ensure_index

CONDITIONS = list(
    itertools.product(
        ["River17", "River28"], ["ModelOak", "ModelElm", "ModelAsh"], ["MAEC", "MAEP"]
    )
)


def write_fixture(path, text: str) -> None:
    """Write deterministic UTF-8/LF test input on every supported platform."""
    path.write_text(text, encoding="utf-8", newline="\n")


@pytest.mark.parametrize("dataset,method,metric", CONDITIONS)
async def test_condition_variants_keep_original_headers_and_values(
    config, tmp_path, dataset, method, metric
):
    tables = []
    for i, data in enumerate(["River17", "River28"], 1):
        tables.append(
            f"Table {i}: Main results on {data}, averaged over three runs.\nMethod MAEC MAEP Units\n"
            + "\n".join(
                f"{model} {i * 10 + j}.1 {i * 10 + j}.2 0.5"
                for j, model in enumerate(["ModelOak", "ModelElm", "ModelAsh"])
            )
            + "\n\n"
        )
    path = tmp_path / "tables.txt"
    write_fixture(path, "".join(tables))
    async with CiteFabricClient(config) as client:
        doc = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": doc.data["fabric_id"]}],
            f"{dataset} {method} {metric} main results",
            retrieval_policy="structured_v3",
        )
        assert result.status == "ok"
        first = result.data["selection_trace"]["ranked_candidates"][0]
        block = client.store.db.execute(
            "SELECT text FROM structure_blocks WHERE id=?", (first["block_id"],)
        ).fetchone()[0]
        assert dataset in block and method in block and metric in block
        assert first["kind"] == "table"
        for hit in result.data["hits"]:
            evidence = client.store.evidence(hit["evidence"]["evidence_id"])
            assert (
                evidence.excerpt
                == path.read_text(encoding="utf-8")[
                    evidence.locator.char_start : evidence.locator.char_end
                ]
            )
        assert all(b["requirements_status"] != "complete" for b in result.data["bundles"])


@pytest.mark.parametrize("number", range(10))
async def test_scope_variants_preserve_negation_and_conditions(config, tmp_path, number):
    name = f"Method{number}"
    path = tmp_path / "scope.txt"
    write_fixture(
        path,
        f"Results\n{name} improved accuracy in the evaluated experiment.\n"
        + "Experimental details and useful observations. " * 60
        + f"\nLimitations\n{name} was tested only on adult samples under fixed lighting. This does not establish performance for children or changing conditions.\nFuture work\n{name} could be tested in additional environments in future research.\n",
    )
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": imported.data["fabric_id"]}],
            f"Does {name} work in all conditions?",
            retrieval_policy="structured_v3",
            max_chars=1500,
        )
        text = "\n".join(h["evidence"]["excerpt"] for h in result.data["hits"])
        assert "only on adult samples" in text
        assert "does not establish performance for children" in text
        assert result.data["returned_chars"] <= 1500


@pytest.mark.parametrize("budget", [500, 800, 1100, 1600, 3000, 6000, 12000, 16000])
async def test_dual_budget_and_old_evidence(config, tmp_path, budget):
    path = tmp_path / "budget.txt"
    write_fixture(
        path,
        "Table 1: Solar19 ModelFir results\nMethod Score Cost\nModelFir 72.1 53.2 8.1\n\n"
        + "Solar19 ModelFir results with explanatory context 🧬. " * 170,
    )
    async with CiteFabricClient(config) as client:
        doc = await client.import_document(path)
        papers = [{"ref": doc.data["fabric_id"]}]
        old = await client.find_evidence(papers, "Solar19 ModelFir", include_context=False)
        old_evidence = old.data["hits"][0]["evidence"]
        receipt = (
            await client.verify_claim(
                "The method performs well", papers, evidence_ids=[old_evidence["evidence_id"]]
            )
        ).data["receipts"][0]
        result = await client.find_evidence(
            papers,
            "Solar19 ModelFir Table 1 results",
            retrieval_policy="structured_v3",
            max_chars=budget,
            max_passages=2,
        )
        assert len(result.data["hits"]) <= 2
        assert result.data["returned_chars"] == sum(
            len(h["evidence"]["excerpt"]) for h in result.data["hits"]
        )
        assert result.data["returned_chars"] <= budget
        assert (
            client.store.evidence(old_evidence["evidence_id"]).model_dump(mode="json")
            == old_evidence
        )
        assert client.store.receipt(receipt["receipt_id"]).model_dump(mode="json") == receipt


async def test_missing_configuration_is_not_certified(config, tmp_path):
    path = tmp_path / "absent.txt"
    write_fixture(path, "Table 1: River17 data\nMethod MAEC MAEP\nModelOak 1.2 2.3 4.5\n")
    async with CiteFabricClient(config) as client:
        doc = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": doc.data["fabric_id"]}],
            "River99 ModelOak main results",
            retrieval_policy="structured_v3",
        )
        trace = result.data["selection_trace"]
        assert "literal:river99" in trace["missing_requirements"]
        assert all(b["requirements_status"] != "complete" for b in result.data["bundles"])


async def test_cancelled_and_concurrent_index_build_is_atomic(config, tmp_path):
    path = tmp_path / "index.txt"
    write_fixture(path, "Table 1: River17 data\nModelOak 1.2 2.3 4.5\n")
    async with CiteFabricClient(config) as client:
        doc = await client.import_document(path)
        extraction = client.store.extraction(doc.data["extraction_id"])
        edition = doc.data["edition_id"]
        task = asyncio.create_task(ensure_index(client.store, extraction, edition))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.store.db.execute("SELECT count(*) FROM structure_indexes").fetchone()[0] == 0
        ids = await asyncio.gather(
            ensure_index(client.store, extraction, edition),
            ensure_index(client.store, extraction, edition),
        )
        assert ids[0] == ids[1]
        assert client.store.db.execute("SELECT count(*) FROM structure_indexes").fetchone()[0] == 1
        assert (
            client.store.db.execute("SELECT count(*) FROM structure_blocks").fetchone()[0]
            == client.store.db.execute("SELECT count(*) FROM structure_fts").fetchone()[0]
        )


async def test_failed_index_falls_back_explicitly(config, tmp_path, monkeypatch):
    import citefabric.evidence_selection as selection

    async def fail(*args):
        raise FabricError("structure_index_limit", "test limit")

    path = tmp_path / "fallback.txt"
    write_fixture(path, "Table 1: River17 study. ModelOak measured 42 percent accuracy.")
    async with CiteFabricClient(config) as client:
        doc = await client.import_document(path)
        monkeypatch.setattr(selection, "ensure_index", fail)
        result = await client.find_evidence(
            [{"ref": doc.data["fabric_id"]}], "River17 Table 1", retrieval_policy="structured_v3"
        )
        assert result.status == "partial"
        assert result.data["retrieval_version"] == "2"
        assert result.data["fallback_reason"] == "structure_index_limit"
        assert result.data["hits"]


def test_migration_backups_are_readable_and_future_schema_is_rejected(config):
    store = Store(config.data_dir)
    store.db.execute("DROP TABLE structure_fts")
    store.db.execute("DROP TABLE structure_blocks")
    store.db.execute("DROP TABLE structure_indexes")
    store.db.execute("PRAGMA user_version=1")
    store.db.commit()
    store.close()
    store = Store(config.data_dir)
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 2
    backup = next((config.data_dir / "backups").glob("schema-1-*.sqlite3"))
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    store.db.execute("PRAGMA user_version=99")
    store.close()
    with pytest.raises(FabricError, match="different CiteFabric version"):
        Store(config.data_dir)


def test_metric_aliases_and_reference_numbers_do_not_collapse():
    plan = plan_query("River17 MAE_C Table 6", True)
    assert plan["reference_terms"] == [{"kind": "table", "number": "6"}]
    assert entity_matches("MAE C", ["maec", "maep"]) == ["maec"]
    assert entity_matches("B ACKTIME", ["backtime"]) == ["backtime"]


async def test_budget_failure_is_distinguished_from_no_candidates(config, tmp_path):
    path = tmp_path / "long-atomic.txt"
    write_fixture(
        path, "Table 1: River17\n" + "An unbroken explanatory sentence without numbers " * 80
    )
    async with CiteFabricClient(config) as client:
        doc = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": doc.data["fabric_id"]}],
            "River17 Table 1",
            retrieval_policy="structured_v3",
            max_chars=500,
        )
        assert not result.data["hits"]
        assert result.status == "partial"
        assert any(o.code == "context_budget_exceeded" for o in result.outcomes)


async def test_reference_context_uses_a_separate_exact_span(config, tmp_path):
    path = tmp_path / "reference.txt"
    write_fixture(
        path,
        "Table 1: River17 measurements\nMethod MAEC MAEP\nModelOak 11.2 22.3 0.4\n\n"
        + "Unrelated details. " * 300
        + "\nRiver17 ModelOak forecasting quality is discussed in Table 1.\n" * 12,
    )
    async with CiteFabricClient(config) as client:
        doc = await client.import_document(path)
        result = await client.find_evidence(
            [{"ref": doc.data["fabric_id"]}],
            "River17 ModelOak forecasting quality",
            retrieval_policy="structured_v3",
            max_chars=6000,
        )
        assert result.data["selection_trace"]["route"] == "lexical_compatibility"
        assert any("11.2 22.3" in h["evidence"]["excerpt"] for h in result.data["hits"])
        assert result.data["returned_chars"] <= 6000
        for bundle in result.data["bundles"]:
            assert set(bundle["evidence_ids"]) <= {
                h["evidence"]["evidence_id"] for h in result.data["hits"]
            }


async def test_structured_evidence_does_not_cross_pages_or_documents(config, tmp_path):
    from io import BytesIO

    from pypdf import PdfReader, PdfWriter

    from .conftest import pdf_bytes

    writer = PdfWriter()
    pages = [
        "Table 1: River17 ModelOak\nModelOak 17.2 28.3 39.4\n",
        "Table 2: River28 ModelElm\nModelElm 71.2 82.3 93.4\n",
    ]
    for text in pages:
        writer.add_page(PdfReader(BytesIO(pdf_bytes(text))).pages[0])
    path = tmp_path / "pages.pdf"
    writer.write(path)
    other = tmp_path / "other.txt"
    write_fixture(other, "Table 1: River17 ModelOak DIFFERENT_DOCUMENT\nModelOak 99.9 99.8 99.7\n")
    async with CiteFabricClient(config) as client:
        doc = await client.import_document(path)
        await client.import_document(other)
        result = await client.find_evidence(
            [{"ref": doc.data["fabric_id"]}],
            "River17 ModelOak Table 1",
            retrieval_policy="structured_v3",
            max_passages=1,
        )
        assert result.data["hits"]
        for hit in result.data["hits"]:
            evidence = client.store.evidence(hit["evidence"]["evidence_id"])
            assert evidence.locator.page == 1
            assert "DIFFERENT_DOCUMENT" not in evidence.excerpt
            assert "River28" not in evidence.excerpt


def test_migration_failure_rolls_back(config):
    store = Store(config.data_dir)
    store.db.execute("DROP TABLE structure_fts")
    store.db.execute("DROP TABLE structure_blocks")
    # Simulate an incompatible existing table: migration must not partially apply.
    store.db.execute("PRAGMA user_version=1")
    store.close()
    with pytest.raises(sqlite3.OperationalError):
        Store(config.data_dir)
    with sqlite3.connect(config.data_dir / "citefabric.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='structure_blocks'"
        ).fetchall()
