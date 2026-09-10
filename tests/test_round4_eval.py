import copy
import json

import pytest
from jsonschema import ValidationError

from scripts import round4_eval as ev
from scripts import round4_synthetic as synth


@pytest.fixture
def queries(tmp_path):
    return synth.make_queries(tmp_path / "input")


@pytest.mark.parametrize(
    "problem",
    [
        "gold_leak",
        "duplicate",
        "cycle",
        "cross_paper",
        "missing_parent",
        "source_path",
        "reviewer",
        "saw_outputs",
        "same_source",
    ],
)
def test_query_contract_rejects_leaks_and_invalid_relationships(queries, problem):
    if problem == "gold_leak":
        queries["intents"][0]["gold"] = {"answer": "secret"}
    elif problem == "duplicate":
        queries["intents"].append(copy.deepcopy(queries["intents"][0]))
    elif problem == "cycle":
        queries["intents"][0]["parent_intent_id"] = "synthetic-variant"
    elif problem == "cross_paper":
        queries["intents"][-1]["parent_intent_id"] = "synthetic1-supported"
    elif problem == "missing_parent":
        queries["intents"][-1]["parent_intent_id"] = "missing"
    elif problem == "source_path":
        queries["papers"][0]["filename"] = "../paper.pdf"
    elif problem == "same_source":
        queries["papers"][1]["sha256"] = queries["papers"][0]["sha256"]
    else:
        queries["status"] = "frozen"
        review = queries["intents"][0]["equivalence_review"]
        if problem == "reviewer":
            review.update(independence="independent_review", reviewer_ids=[review["author_id"]])
        else:
            review["saw_retrieval_outputs"] = True
    with pytest.raises((ValueError, ValidationError)):
        ev.validate_queries(queries)


def test_prior_family_and_source_overlap_rejected(queries):
    with pytest.raises(ValueError, match="family overlaps"):
        ev.validate_queries(queries, [queries])
    previous = copy.deepcopy(queries)
    for p in previous["papers"]:
        p["family_id"] += "-renamed"
    with pytest.raises(ValueError, match="Source overlaps"):
        ev.validate_queries(queries, [previous])


def test_source_hash_failure_writes_nothing(queries, tmp_path):
    (tmp_path / "input/synthetic0.pdf").write_bytes(b"changed")
    with pytest.raises(ValueError, match="PDF hash mismatch"):
        ev.validate_sources(queries, tmp_path / "input")
    assert not (tmp_path / "prepared").exists()


def test_cluster_statistics_do_not_count_translations_as_papers():
    rows = [{"family_id": "a", "hit": True}] * 10 + [{"family_id": "b", "hit": False}]
    m = ev.metric(rows, lambda _: True, lambda r: r["hit"])
    assert m["numerator"] == 10 and m["denominator"] == 11
    assert m["paper_macro"] == 0.5
    paired = ev.paired_interval(m["per_family"], m["per_family"])
    assert paired["delta"] == 0 and paired["ci95"] == [0, 0]
    assert paired["clusters"] == 2
    assert ev.paired_interval({"a": {"rate": 1}}, {"a": {"rate": 1}}) is None


async def test_seal_prevents_query_code_and_gold_drift(tmp_path):
    queries = synth.make_queries(tmp_path / "input")
    queries["status"] = "frozen"
    queries["split"] = "holdout"
    qpath = tmp_path / "frozen-queries.json"
    ev.write(qpath, queries)
    prepared = tmp_path / "prepared"
    preparation = await ev.prepare(qpath, tmp_path / "input", prepared)
    gold = synth.make_gold(qpath, preparation)
    ev.write(tmp_path / "gold.json", gold)
    with pytest.raises(ValueError, match="requires a seal"):
        await ev.run(prepared, tmp_path / "unsealed")
    assert not (tmp_path / "unsealed").exists()
    commitment = ev.seal(
        prepared, tmp_path / "gold.json", tmp_path / "seal.json", "synthetic-custodian"
    )
    assert commitment["independence_verified"] is False
    with pytest.raises(FileExistsError):
        ev.seal(prepared, tmp_path / "gold.json", tmp_path / "seal.json", "synthetic-custodian")
    bad_seal = copy.deepcopy(commitment)
    bad_seal["prepared_sha256"] = "f" * 64
    ev.write(tmp_path / "bad-seal.json", bad_seal)
    with pytest.raises(ValueError, match="Seal preparation mismatch"):
        await ev.run(prepared, tmp_path / "bad-run", seal_path=tmp_path / "bad-seal.json")
    with pytest.raises(ValueError, match="parameters differ"):
        await ev.run(
            prepared, tmp_path / "bad-budget", max_chars=12000, seal_path=tmp_path / "seal.json"
        )
    await ev.run(prepared, tmp_path / "sealed-run", seal_path=tmp_path / "seal.json")
    changed_gold = copy.deepcopy(gold)
    changed_gold["cases"][0]["rationale"] = "Edited after sealing"
    ev.write(tmp_path / "changed-gold.json", changed_gold)
    with pytest.raises(ValueError, match="Gold changed after sealing"):
        ev.score(
            tmp_path / "sealed-run",
            tmp_path / "unused-package.json",
            tmp_path / "unused-key.json",
            tmp_path / "changed-gold.json",
            [],
            tmp_path / "never.json",
        )


async def test_import_failure_stays_in_matrix(tmp_path):
    queries = synth.make_queries(tmp_path / "input")
    # Valid blank PDF: import should return OCR-required, not disappear from the cohort.
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    path = tmp_path / "input/synthetic0.pdf"
    writer.write(path)
    queries["papers"][0]["sha256"] = ev.digest(path.read_bytes())
    qpath = tmp_path / "queries.json"
    ev.write(qpath, queries)
    prepared = tmp_path / "prepared"
    await ev.prepare(qpath, tmp_path / "input", prepared)
    data = await ev.run(prepared, tmp_path / "run")
    assert len(data["rows"]) == 112
    failed = [r for r in data["rows"] if r["paper_id"] == "synthetic0"]
    assert len(failed) == 64
    assert all(r["status"] == "import_failed" and not r["replay_integrity"] for r in failed)
    package = ev.blind(tmp_path / "run", tmp_path / "review", tmp_path / "key.json")
    assert len(package["items"]) == 28
    assert all(not i["evidence"] for i in package["items"] if i["paper_id"] == "synthetic0")


async def test_synthetic_end_to_end_real_stdio(tmp_path, monkeypatch):
    directory = tmp_path / "demo"
    original_run, original_read = ev.run, ev.read

    async def guarded_run(*args, **kwargs):
        def query_only_read(path):
            assert path.name in {"queries.json", "prepared.json", "fixture.schema.json"}
            return original_read(path)

        with monkeypatch.context() as context:
            context.setattr(ev, "read", query_only_read)
            return await original_run(*args, **kwargs)

    monkeypatch.setattr(ev, "run", guarded_run)
    report = await synth.demo(directory)
    assert report["promotion"]["status"] == "not_evaluated"
    assert report["failure_counts"] == {"v2": 0, "structured_v3": 0}
    for language in ev.LANGUAGES:
        for policy in ev.POLICIES:
            assert report["metrics"][language][policy]["esr"]["denominator"] == 4
            assert report["metrics"][language][policy]["insufficient_mismatch"]["denominator"] == 2
    data = ev.read(directory / "run/run.json")
    assert len(data["rows"]) == 112
    assert all(r["replay_integrity"] and r["budget_ok"] for r in data["rows"])
    for row in data["rows"]:
        assert row["response_bytes"] == sum(len(ev.encoded(m)) for m in row["response_messages"])
        assert row["audit_bytes"] == sum(len(ev.encoded(m)) for m in row["audit_messages"])
        assert row["response_bytes"] > len(ev.encoded(row["retrieval"]))
    package_path = directory / "review/items.json"
    package = ev.read(package_path)
    assert len(package["items"]) == 28
    serialized = json.dumps(package)
    for forbidden in (
        "structured_v3",
        '"policy"',
        "selection_trace",
        "evidence_id",
        "query_seconds",
    ):
        assert forbidden not in serialized
    with pytest.raises(ValueError, match="already used"):
        await ev.run(directory / "prepared", directory / "repeat")
    with pytest.raises(ValueError, match="outside reviewer"):
        ev.blind(directory / "run", directory / "bad-review", directory / "bad-review/key.json")

    gold = ev.read(directory / "gold.json")
    snapshots = ev.read(directory / "prepared/extractions.json")
    queries_path = directory / "prepared/queries.json"
    for problem in ("hash", "span", "foreign", "insufficient", "missing_case", "unit"):
        bad = copy.deepcopy(gold)
        if problem == "hash":
            bad["queries_sha256"] = "f" * 64
        elif problem == "span":
            bad["cases"][0]["spans"][0]["quote"] = "x" * len(bad["cases"][0]["spans"][0]["quote"])
        elif problem == "foreign":
            bad["cases"][0]["sufficient_sets"] = [["missing"]]
        elif problem == "insufficient":
            bad["cases"][2]["absence_review"] = None
        elif problem == "unit":
            bad["cases"][0]["spans"][0]["unit_index"] = 9
        else:
            bad["cases"].pop()
        with pytest.raises((ValueError, ValidationError)):
            ev.validate_gold(queries_path, bad, snapshots)

    visual_only = copy.deepcopy(gold)
    missing_snapshot = copy.deepcopy(snapshots)
    missing_snapshot["synthetic0"] = None
    for case in visual_only["cases"]:
        if case["paper_id"] == "synthetic0":
            case["spans"] = []
            case["extraction_text_sha256"] = None
            case["tags"].append("extraction_gap")
            for requirement in case["requirements"]:
                requirement.update(
                    span_ids=[],
                    visual_requirements=[{"page": 1, "description": "Visual-only reference"}],
                )
    ev.validate_gold(queries_path, visual_only, missing_snapshot)

    reviews = [directory / f"synthetic-review-{label}.json" for label in ("a", "b")]
    review = ev.read(reviews[0])
    cases = {c["intent_id"]: c for c in gold["cases"]}
    incomplete = copy.deepcopy(review)
    incomplete["ratings"].pop()
    with pytest.raises(ValueError, match="Every blind item"):
        ev.validate_ratings(incomplete, package, cases)
    invalid_alias = copy.deepcopy(review)
    invalid_alias["ratings"][0]["evidence_aliases"] = ["E99999"]
    with pytest.raises(ValueError, match="Unknown cited"):
        ev.validate_ratings(invalid_alias, package, cases)
    disagree = copy.deepcopy(ev.read(reviews[1]))
    target = next(r for r in disagree["ratings"] if r["sufficiency"] == "complete")
    target.update(sufficiency="partial", requirements={"r1": "ambiguous"})
    disagreement_path = directory / "disagree.json"
    ev.write(disagreement_path, disagree)
    args = (
        directory / "run",
        package_path,
        directory / "private-key.json",
        directory / "gold.json",
        [reviews[0], disagreement_path],
    )
    with pytest.raises(ValueError, match="Unresolved reviewer"):
        ev.score(*args, directory / "unresolved.json")
    assert not (directory / "unresolved.json").exists()
    adjudication = copy.deepcopy(review)
    adjudication["reviewer_id"] = "synthetic-adjudicator"
    ev.write(directory / "adjudication.json", adjudication)
    resolved = ev.score(*args, directory / "resolved.json", directory / "adjudication.json")
    assert len(resolved["review_disagreements"]) == 1
    assert resolved["agreement_before_adjudication"]["sufficiency"] < 1
