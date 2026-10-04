import copy
import json

import pytest

from scripts import round4_eval as ev
from scripts import round4_paired_review as paired
from scripts import round4_synthetic as synth


def _filled_review(template, package, reviewer_id, flip_first=False):
    review = copy.deepcopy(template)
    review["reviewer_id"] = reviewer_id
    review["reviewer_declaration"] = {
        "independent": True,
        "saw_private_key": False,
        "saw_other_review": False,
    }
    pairs = {pair["pair_id"]: pair for pair in package["pairs"]}
    for pair_rating in review["ratings"]:
        pair = pairs[pair_rating["pair_id"]]
        verdict = pair["reference"]["verdict"]
        for candidate in pair_rating["candidates"]:
            package_candidate = next(
                item
                for item in pair["candidates"]
                if item["candidate_id"] == candidate["candidate_id"]
            )
            candidate["sufficiency"] = "not_applicable" if verdict == "insufficient" else "complete"
            candidate["requirements"] = {key: "present" for key in candidate["requirements"]}
            candidate["harmful_mismatch"] = False
            candidate["limitation_preserved"] = (
                True if pair["reference"]["limitation_rating_required"] else None
            )
            candidate["failure_stage"] = "none"
            candidate["evidence_aliases"] = (
                [package_candidate["evidence"][0]["alias"]] if package_candidate["evidence"] else []
            )
            candidate["rationale"] = "Synthetic oracle rating."
    if flip_first:
        first = review["ratings"][0]["candidates"][0]
        first["harmful_mismatch"] = True
        first["mismatch_types"] = ["wrong_scope"]
    return review


@pytest.mark.asyncio
async def test_paired_review_build_validate_and_score(tmp_path):
    queries = synth.make_queries(tmp_path / "input")
    queries["status"] = "frozen"
    queries["split"] = "holdout"
    qpath = tmp_path / "queries.json"
    ev.write(qpath, queries)
    prepared = tmp_path / "prepared"
    preparation = await ev.prepare(qpath, tmp_path / "input", prepared)
    gold = synth.make_gold(qpath, preparation)
    ev.write(tmp_path / "gold.json", gold)
    ev.seal(prepared, tmp_path / "gold.json", tmp_path / "seal.json", "custodian")
    await ev.run(prepared, tmp_path / "run", seal_path=tmp_path / "seal.json")

    package = paired.build(
        tmp_path / "run",
        tmp_path / "gold.json",
        tmp_path / "review",
        tmp_path / "private-key.json",
        7,
    )
    assert len(package["pairs"]) == len(queries["intents"]) * 2
    assert all(len(pair["candidates"]) == 2 for pair in package["pairs"])
    assert all(type(pair["candidate_evidence_identical"]) is bool for pair in package["pairs"])
    serialized = json.dumps(package)
    assert "offline_structured_v6" not in serialized
    assert '"policy"' not in serialized
    assert (
        paired.validate_package(
            tmp_path / "run",
            tmp_path / "gold.json",
            tmp_path / "review/items.json",
            tmp_path / "private-key.json",
        )["candidates"]
        == len(queries["intents"]) * 4
    )

    template = ev.read(tmp_path / "review/rating-template.json")
    review_a = _filled_review(template, package, "reviewer-a")
    review_b = _filled_review(template, package, "reviewer-b")
    ev.write(tmp_path / "review-a.json", review_a)
    ev.write(tmp_path / "review-b.json", review_b)
    report = paired.score(
        tmp_path / "run",
        tmp_path / "review/items.json",
        tmp_path / "private-key.json",
        tmp_path / "gold.json",
        [tmp_path / "review-a.json", tmp_path / "review-b.json"],
        tmp_path / "scores.json",
    )
    assert len(report["rows"]) == len(queries["intents"]) * 4
    assert report["review_disagreements"] == []
    assert report["metrics"]["en"]["v2"]["esr"]["denominator"] == 4
    assert report["metrics"]["zh"]["offline_structured_v6"]["esr"]["denominator"] == 4


def test_review_requires_independence_and_resolves_disagreements(tmp_path):
    package = {
        "pairs": [
            {
                "pair_id": "p",
                "reference": {
                    "verdict": "supported",
                    "requirements": [{"requirement_id": "r1"}],
                    "sufficient_sets": [["r1"]],
                    "limitation_rating_required": False,
                },
                "candidates": [{"candidate_id": "c", "label": "A", "evidence": []}],
            }
        ]
    }
    template = {
        "reviewer_id": "r",
        "reviewer_declaration": {
            "independent": False,
            "saw_private_key": False,
            "saw_other_review": False,
        },
        "ratings": [
            {
                "pair_id": "p",
                "candidates": [
                    {
                        "candidate_id": "c",
                        "label": "A",
                        "sufficiency": "none",
                        "requirements": {"r1": "missing"},
                        "harmful_mismatch": False,
                        "mismatch_types": [],
                        "limitation_preserved": None,
                        "failure_stage": "selection",
                        "evidence_aliases": [],
                        "rationale": "No evidence was returned.",
                    }
                ],
            }
        ],
    }
    with pytest.raises(ValueError, match="declare independence"):
        paired.validate_review(template, package)
    template["reviewer_declaration"]["independent"] = True
    assert paired.validate_review(template, package)["c"]["sufficiency"] == "none"
    template["reviewer_declaration"]["saw_other_review"] = True
    assert (
        paired.validate_review(template, package, adjudication=True)["c"]["sufficiency"] == "none"
    )
