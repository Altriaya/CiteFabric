"""Build and score a policy-blind paired Round 4 evidence review.

The reviewer package contains one A/B pair per intent and language.  Policy
identities and evidence IDs stay in a private key outside the review directory.
The package includes the frozen gold requirements needed to apply the rubric,
but never identifies which candidate is the baseline or candidate policy.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import uuid
from pathlib import Path

try:
    from scripts import round4_eval as ev
except ImportError:  # pragma: no cover - direct script execution
    import round4_eval as ev


POLICIES = ("v2", "offline_structured_v6")
LABELS = ("A", "B")
RATING_FIELDS = (
    "sufficiency",
    "requirements",
    "harmful_mismatch",
    "mismatch_types",
    "limitation_preserved",
    "failure_stage",
)


def _candidate_template(candidate: dict, requirement_ids: list[str]) -> dict:
    return {
        "candidate_id": candidate["candidate_id"],
        "label": candidate["label"],
        "sufficiency": None,
        "requirements": {requirement_id: None for requirement_id in requirement_ids},
        "harmful_mismatch": None,
        "mismatch_types": [],
        "limitation_preserved": None,
        "failure_stage": None,
        "evidence_aliases": [],
        "rationale": "",
    }


def build(run_dir: Path, gold_path: Path, output_dir: Path, key_path: Path, seed: int) -> dict:
    ev.require(not output_dir.exists(), "Review output already exists")
    ev.require(not key_path.exists(), "Private key already exists")
    ev.require(
        not key_path.resolve().is_relative_to(output_dir.resolve()),
        "Private key must be outside reviewer directory",
    )
    data = ev.read(run_dir / "run.json")
    queries_path = run_dir / "queries.json"
    queries = ev.read(queries_path)
    gold = ev.read(gold_path)
    cases = ev.validate_gold(queries_path, gold, data["preparation"]["snapshots"])
    ev.require(
        data["queries_sha256"] == ev.digest(queries_path.read_bytes()), "Run queries changed"
    )
    if data.get("seal"):
        ev.require(data["seal"]["gold_sha256"] == ev.digest(gold_path.read_bytes()), "Gold changed")
    papers, intents = ev.validate_queries(queries)
    selected = {
        (row["intent_id"], row["language"], row["policy"]): row
        for row in ev.selected_rows(data, queries)
        if row["policy"] in POLICIES
    }
    expected = {
        (intent_id, language, policy)
        for intent_id in intents
        for language in ev.LANGUAGES
        for policy in POLICIES
    }
    ev.require(set(selected) == expected, "Paired run rows are missing or duplicated")

    rng = random.Random(seed)
    groups = [(intent_id, language) for intent_id in intents for language in ev.LANGUAGES]
    rng.shuffle(groups)
    pairs, mapping = [], {}
    for intent_id, language in groups:
        intent = intents[intent_id]
        case = cases[intent_id]
        pair_id = uuid.UUID(int=rng.getrandbits(128)).hex
        policy_order = list(POLICIES)
        rng.shuffle(policy_order)
        candidates = []
        for label, policy in zip(LABELS, policy_order, strict=True):
            row = selected[(intent_id, language, policy)]
            candidate_id = uuid.UUID(int=rng.getrandbits(128)).hex
            evidence, evidence_ids = [], {}
            for number, item in enumerate(row["evidence"], 1):
                alias = f"E{number}"
                locator = item["locator"]
                evidence.append(
                    {
                        "alias": alias,
                        "excerpt": item["excerpt"],
                        "page": locator["page"],
                        "start": locator["char_start"],
                        "end": locator["char_end"],
                    }
                )
                evidence_ids[alias] = item["evidence_id"]
            candidates.append({"candidate_id": candidate_id, "label": label, "evidence": evidence})
            mapping[candidate_id] = {
                "pair_id": pair_id,
                "intent_id": intent_id,
                "language": language,
                "policy": policy,
                "evidence_ids": evidence_ids,
            }
        pairs.append(
            {
                "pair_id": pair_id,
                "intent_id": intent_id,
                "language": language,
                "paper_id": intent["paper_id"],
                "title": papers[intent["paper_id"]]["title"],
                "edition": papers[intent["paper_id"]]["edition_label"],
                "query": intent["query"][language],
                "claim": intent["claim"][language],
                "reference": {
                    "verdict": case["reference_verdict"],
                    "requirements": [
                        {
                            "requirement_id": requirement["requirement_id"],
                            "dimension": requirement["dimension"],
                            "description": requirement["description"],
                        }
                        for requirement in case["requirements"]
                    ],
                    "sufficient_sets": case["sufficient_sets"],
                    "limitation_rating_required": case["reference_verdict"] != "insufficient"
                    and "scope_limitation" in case["tags"],
                },
                "candidate_evidence_identical": candidates[0]["evidence"]
                == candidates[1]["evidence"],
                "candidates": candidates,
            }
        )

    package = {
        "kind": "round4_paired_blind",
        "run_id": data["run_id"],
        "policies_hidden": True,
        "pairs": pairs,
    }
    output_dir.mkdir(parents=True)
    ev.write(output_dir / "items.json", package)
    package_hash = ev.digest((output_dir / "items.json").read_bytes())
    template = {
        "reviewer_id": "REPLACE_WITH_REVIEWER_ID",
        "reviewer_declaration": {
            "independent": None,
            "saw_private_key": None,
            "saw_other_review": None,
        },
        "package_sha256": package_hash,
        "ratings": [
            {
                "pair_id": pair["pair_id"],
                "candidates": [
                    _candidate_template(
                        candidate,
                        [r["requirement_id"] for r in pair["reference"]["requirements"]],
                    )
                    for candidate in pair["candidates"]
                ],
            }
            for pair in pairs
        ],
    }
    ev.write(output_dir / "rating-template.json", template)
    ev.write(
        key_path,
        {
            "kind": "round4_paired_blind_key",
            "run_sha256": ev.digest((run_dir / "run.json").read_bytes()),
            "gold_sha256": ev.digest(gold_path.read_bytes()),
            "package_sha256": package_hash,
            "seed": seed,
            "policies": list(POLICIES),
            "mapping": mapping,
        },
    )
    return package


def _unique(values: list[dict], key: str, message: str) -> dict:
    result = {value[key]: value for value in values}
    ev.require(len(result) == len(values), message)
    return result


def validate_review(review: dict, package: dict, *, adjudication: bool = False) -> dict:
    reviewer_id = review.get("reviewer_id")
    ev.require(
        isinstance(reviewer_id, str) and reviewer_id not in {"", "REPLACE_WITH_REVIEWER_ID"},
        "Missing reviewer identity",
    )
    declaration = review.get("reviewer_declaration", {})
    ev.require(declaration.get("independent") is True, "Reviewer must declare independence")
    ev.require(declaration.get("saw_private_key") is False, "Reviewer saw private key")
    ev.require(
        declaration.get("saw_other_review") is adjudication,
        "Initial reviewers must not see another review; adjudicators must declare that they did",
    )
    pairs = _unique(package["pairs"], "pair_id", "Duplicate package pair")
    ratings = _unique(review.get("ratings", []), "pair_id", "Duplicate rated pair")
    ev.require(set(ratings) == set(pairs), "Every pair must be scored exactly once")
    flattened = {}
    for pair_id, pair in pairs.items():
        reference = pair["reference"]
        requirement_ids = {r["requirement_id"] for r in reference["requirements"]}
        expected_candidates = _unique(pair["candidates"], "candidate_id", "Duplicate candidate")
        rated_candidates = _unique(
            ratings[pair_id].get("candidates", []), "candidate_id", "Duplicate candidate rating"
        )
        ev.require(
            set(rated_candidates) == set(expected_candidates), "Candidate ratings incomplete"
        )
        for candidate_id, rating in rated_candidates.items():
            candidate = expected_candidates[candidate_id]
            ev.require(rating.get("label") == candidate["label"], "Candidate label changed")
            answerable = reference["verdict"] != "insufficient"
            allowed = {"complete", "partial", "none"} if answerable else {"not_applicable"}
            ev.require(rating.get("sufficiency") in allowed, "Invalid sufficiency")
            requirements = rating.get("requirements", {})
            ev.require(set(requirements) == requirement_ids, "Incomplete requirement ratings")
            ev.require(
                set(requirements.values()) <= {"present", "missing", "ambiguous"},
                "Invalid requirement state",
            )
            if rating["sufficiency"] == "complete":
                ev.require(
                    any(
                        all(requirements[requirement_id] == "present" for requirement_id in group)
                        for group in reference["sufficient_sets"]
                    ),
                    "Complete rating lacks a sufficient requirement set",
                )
            ev.require(type(rating.get("harmful_mismatch")) is bool, "Missing mismatch judgment")
            mismatch_types = set(rating.get("mismatch_types", []))
            ev.require(
                mismatch_types
                <= {"wrong_dataset", "wrong_model", "wrong_metric", "wrong_scope", "wrong_version"},
                "Invalid mismatch type",
            )
            ev.require(
                bool(mismatch_types) == rating["harmful_mismatch"], "Mismatch is inconsistent"
            )
            expected_limitation = reference["limitation_rating_required"]
            ev.require(
                type(rating.get("limitation_preserved")) is bool
                if expected_limitation
                else rating.get("limitation_preserved") is None,
                "Invalid limitation judgment",
            )
            ev.require(
                rating.get("failure_stage")
                in {
                    "import",
                    "extraction",
                    "candidate_recall",
                    "selection",
                    "budget",
                    "relation_ambiguity",
                    "language",
                    "annotation",
                    "none",
                },
                "Invalid failure stage",
            )
            aliases = {e["alias"] for e in candidate["evidence"]}
            ev.require(set(rating.get("evidence_aliases", [])) <= aliases, "Unknown evidence alias")
            ev.require(str(rating.get("rationale", "")).strip(), "Missing rationale")
            if (
                rating["sufficiency"] in {"complete", "partial"}
                or rating["harmful_mismatch"]
                or rating["limitation_preserved"]
            ):
                ev.require(rating["evidence_aliases"], "Evidence judgment has no cited excerpt")
            flattened[candidate_id] = rating
    return flattened


def _metric(rows: list[dict], predicate, value) -> dict:
    return ev.metric(rows, predicate, value)


def score(
    run_dir: Path,
    package_path: Path,
    key_path: Path,
    gold_path: Path,
    review_paths: list[Path],
    output_path: Path,
    adjudication_path: Path | None = None,
) -> dict:
    ev.require(not output_path.exists(), "Score output already exists")
    ev.require(len(review_paths) == 2, "Exactly two independent reviews are required")
    data = ev.read(run_dir / "run.json")
    queries_path = run_dir / "queries.json"
    queries = ev.read(queries_path)
    gold = ev.read(gold_path)
    cases = ev.validate_gold(queries_path, gold, data["preparation"]["snapshots"])
    papers, intents = ev.validate_queries(queries)
    package, key = ev.read(package_path), ev.read(key_path)
    ev.require(package["run_id"] == data["run_id"], "Package belongs to another run")
    ev.require(key["package_sha256"] == ev.digest(package_path.read_bytes()), "Package changed")
    ev.require(key["run_sha256"] == ev.digest((run_dir / "run.json").read_bytes()), "Run changed")
    ev.require(key["gold_sha256"] == ev.digest(gold_path.read_bytes()), "Gold changed")
    reviews = [ev.read(path) for path in review_paths]
    ev.require(reviews[0]["reviewer_id"] != reviews[1]["reviewer_id"], "Reviewers must differ")
    for review in reviews:
        ev.require(review.get("package_sha256") == key["package_sha256"], "Review hash mismatch")
    ratings = [validate_review(review, package) for review in reviews]
    conflicts = [
        candidate_id
        for candidate_id in ratings[0]
        if any(
            ratings[0][candidate_id][field] != ratings[1][candidate_id][field]
            for field in RATING_FIELDS
        )
    ]
    adjudicated = None
    if adjudication_path:
        adjudication = ev.read(adjudication_path)
        ev.require(
            adjudication["reviewer_id"] not in {r["reviewer_id"] for r in reviews},
            "Adjudicator must differ from reviewers",
        )
        ev.require(
            adjudication.get("package_sha256") == key["package_sha256"],
            "Adjudication hash mismatch",
        )
        adjudicated = validate_review(adjudication, package, adjudication=True)
    ev.require(not conflicts or adjudicated is not None, "Unresolved disagreement")

    selected = {
        (row["intent_id"], row["language"], row["policy"]): row
        for row in ev.selected_rows(data, queries)
        if row["policy"] in POLICIES
    }
    package_pairs = _unique(package["pairs"], "pair_id", "Duplicate package pair")
    package_candidates = {
        candidate["candidate_id"]: (pair, candidate)
        for pair in package_pairs.values()
        for candidate in pair["candidates"]
    }
    ev.require(set(package_candidates) == set(key["mapping"]), "Private mapping is incomplete")
    rows = []
    for candidate_id, mapping in key["mapping"].items():
        pair, candidate = package_candidates[candidate_id]
        ev.require(pair["pair_id"] == mapping["pair_id"], "Pair mapping changed")
        row = selected[(mapping["intent_id"], mapping["language"], mapping["policy"])]
        ev.require(
            mapping["evidence_ids"]
            == {f"E{n}": e["evidence_id"] for n, e in enumerate(row["evidence"], 1)},
            "Evidence mapping changed",
        )
        expected_evidence = [
            {
                "alias": f"E{n}",
                "excerpt": e["excerpt"],
                "page": e["locator"]["page"],
                "start": e["locator"]["char_start"],
                "end": e["locator"]["char_end"],
            }
            for n, e in enumerate(row["evidence"], 1)
        ]
        ev.require(candidate["evidence"] == expected_evidence, "Blind evidence changed")
        rating = (
            adjudicated[candidate_id] if candidate_id in conflicts else ratings[0][candidate_id]
        )
        case = cases[mapping["intent_id"]]
        usable = (
            row["status"] in {"ok", "partial", "no_results"}
            and row["replay_integrity"]
            and row.get("budget_ok", False)
        )
        rows.append(
            {
                **mapping,
                "candidate_id": candidate_id,
                "family_id": papers[row["paper_id"]]["family_id"],
                "paper_id": row["paper_id"],
                "domain": papers[row["paper_id"]]["domain"],
                "independent_intent": intents[mapping["intent_id"]]["parent_intent_id"] is None,
                "verdict": case["reference_verdict"],
                "tags": case["tags"],
                "rating": rating,
                "usable": usable,
                "esr": usable
                and rating["sufficiency"] == "complete"
                and not rating["harmful_mismatch"],
            }
        )

    metrics, paired = {}, {}
    for language in ev.LANGUAGES:
        metrics[language] = {}
        for policy in POLICIES:
            subset = [
                r
                for r in rows
                if r["independent_intent"] and r["language"] == language and r["policy"] == policy
            ]
            metrics[language][policy] = {
                "esr": _metric(
                    subset, lambda r: r["verdict"] != "insufficient", lambda r: r["esr"]
                ),
                "supported_esr": _metric(
                    subset, lambda r: r["verdict"] == "supported", lambda r: r["esr"]
                ),
                "contradicted_esr": _metric(
                    subset, lambda r: r["verdict"] == "contradicted", lambda r: r["esr"]
                ),
                "limitation": _metric(
                    subset,
                    lambda r: r["verdict"] != "insufficient" and "scope_limitation" in r["tags"],
                    lambda r: r["usable"] and r["rating"]["limitation_preserved"],
                ),
                "condition_harmful_mismatch": _metric(
                    subset,
                    lambda r: "condition_counterexample" in r["tags"],
                    lambda r: r["rating"]["harmful_mismatch"],
                ),
                "insufficient_harmful_mismatch": _metric(
                    subset,
                    lambda r: r["verdict"] == "insufficient",
                    lambda r: r["rating"]["harmful_mismatch"],
                ),
            }
        paired[language] = ev.paired_interval(
            metrics[language]["v2"]["esr"]["per_family"],
            metrics[language]["offline_structured_v6"]["esr"]["per_family"],
        )

    agreement = {
        field: statistics.mean(
            ratings[0][candidate_id][field] == ratings[1][candidate_id][field]
            for candidate_id in ratings[0]
        )
        for field in ("sufficiency", "harmful_mismatch", "limitation_preserved")
    }
    report = {
        "kind": "round4_paired_scores",
        "run_id": data["run_id"],
        "policies": list(POLICIES),
        "metrics": metrics,
        "paired_esr": paired,
        "reviewers": [r["reviewer_id"] for r in reviews],
        "adjudicator": ev.read(adjudication_path)["reviewer_id"] if adjudication_path else None,
        "agreement_before_adjudication": agreement,
        "review_disagreements": conflicts,
        "rows": rows,
        "input_hashes": {
            "run": ev.digest((run_dir / "run.json").read_bytes()),
            "gold": ev.digest(gold_path.read_bytes()),
            "package": ev.digest(package_path.read_bytes()),
            "key": ev.digest(key_path.read_bytes()),
            "reviews": [ev.digest(path.read_bytes()) for path in review_paths],
            "adjudication": ev.digest(adjudication_path.read_bytes())
            if adjudication_path
            else None,
        },
        "promotion": {
            "status": "not_evaluated",
            "reason": "Human scores inform G2; G0, G1, G3 and an explicit promotion decision remain separate.",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ev.write(output_path, report)
    return report


def validate_package(run_dir: Path, gold_path: Path, package_path: Path, key_path: Path) -> dict:
    data = ev.read(run_dir / "run.json")
    queries_path = run_dir / "queries.json"
    queries = ev.read(queries_path)
    gold = ev.read(gold_path)
    ev.validate_gold(queries_path, gold, data["preparation"]["snapshots"])
    package, key = ev.read(package_path), ev.read(key_path)
    ev.require(package["kind"] == "round4_paired_blind", "Wrong package kind")
    ev.require(package["run_id"] == data["run_id"], "Package belongs to another run")
    ev.require(key["package_sha256"] == ev.digest(package_path.read_bytes()), "Package changed")
    ev.require(key["run_sha256"] == ev.digest((run_dir / "run.json").read_bytes()), "Run changed")
    ev.require(key["gold_sha256"] == ev.digest(gold_path.read_bytes()), "Gold changed")
    pairs = _unique(package["pairs"], "pair_id", "Duplicate pair")
    ev.require(len(pairs) == len(queries["intents"]) * len(ev.LANGUAGES), "Pair count mismatch")
    candidate_ids = {
        candidate["candidate_id"] for pair in pairs.values() for candidate in pair["candidates"]
    }
    ev.require(len(candidate_ids) == len(pairs) * 2, "Candidate count mismatch")
    ev.require(candidate_ids == set(key["mapping"]), "Private mapping mismatch")

    def contains_policy_identity(value) -> bool:
        if isinstance(value, dict):
            if "policy" in value or "policies" in value:
                return True
            return any(contains_policy_identity(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_policy_identity(item) for item in value)
        # Literal "v2" can legitimately occur in paper text.  Only an exact
        # internal policy value is a leak; substrings in excerpts are content.
        return isinstance(value, str) and value in POLICIES

    ev.require(not contains_policy_identity(package), "Policy identity leaked")
    return {
        "pairs": len(pairs),
        "candidates": len(candidate_ids),
        "package_sha256": key["package_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--run-dir", type=Path, required=True)
    builder.add_argument("--gold", type=Path, required=True)
    builder.add_argument("--output-dir", type=Path, required=True)
    builder.add_argument("--private-key", type=Path, required=True)
    builder.add_argument("--seed", type=int, default=20261005)
    validator = commands.add_parser("validate")
    validator.add_argument("--run-dir", type=Path, required=True)
    validator.add_argument("--gold", type=Path, required=True)
    validator.add_argument("--package", type=Path, required=True)
    validator.add_argument("--private-key", type=Path, required=True)
    scorer = commands.add_parser("score")
    scorer.add_argument("--run-dir", type=Path, required=True)
    scorer.add_argument("--gold", type=Path, required=True)
    scorer.add_argument("--package", type=Path, required=True)
    scorer.add_argument("--private-key", type=Path, required=True)
    scorer.add_argument("--review", type=Path, action="append", required=True)
    scorer.add_argument("--adjudication", type=Path)
    scorer.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        package = build(args.run_dir, args.gold, args.output_dir, args.private_key, args.seed)
        print(
            f"Built {len(package['pairs'])} blind pairs and {len(package['pairs']) * 2} candidates."
        )
    elif args.command == "validate":
        summary = validate_package(args.run_dir, args.gold, args.package, args.private_key)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        score(
            args.run_dir,
            args.package,
            args.private_key,
            args.gold,
            args.review,
            args.output,
            args.adjudication,
        )


if __name__ == "__main__":
    main()
