"""Prepare, validate and score the opened semantic-assessment-v2 experiment.

The runner never changes retrieval. It consumes already frozen evidence packages,
keeps gold out of model prompts, and applies the deterministic policy only after a
model response passes schema, evidence-membership and budget validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from citefabric.models import FabricError, Model
from citefabric.semantic import SemanticAssessment, semantic_verdict, validate_evidence_budget

Tier = Literal["single", "double", "four"]
TIERS = ("single", "double", "four")


class TierAssessment(SemanticAssessment):
    tier: Tier


class IntentAssessments(Model):
    intent_id: str
    judgments: list[TierAssessment] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def complete_tiers(self):
        tiers = [item.tier for item in self.judgments]
        if len(set(tiers)) != len(tiers) or set(tiers) != set(TIERS):
            raise ValueError("each intent requires exactly one judgment for every tier")
        return self


class AssessmentBatch(Model):
    contract_version: Literal["semantic-assessment-v2"] = "semantic-assessment-v2"
    intents: list[IntentAssessments]

    @model_validator(mode="after")
    def unique_intents(self):
        identifiers = [item.intent_id for item in self.intents]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("intent IDs must be unique")
        return self


PROMPT = """You assess Chinese scientific claims using only supplied excerpts from one English paper.

For every intent and evidence tier, report three independent axes:
1. coverage: complete only when every material condition is present; partial when direct evidence and an unresolved condition coexist; none when every material condition is missing or ambiguous.
2. relation: supports, contradicts_same_scope, or not_established.
3. absence_basis: not_applicable, explicit_exhaustive_absence, explicit_lack_of_evidence, or unknown_from_excerpts.

List every material claim condition needed for the judgment, including subject, dataset or population, model or method, version, metric, value, unit, direction, baseline, time, scope, and causality when applicable. Mark each condition matched, contradicted_same_scope, missing, or ambiguous.

Use contradicts_same_scope only for mutually exclusive evidence under the same subject, dataset, population, model, method, version, metric, unit, baseline, time, and scope. A result from a different configuration is not a contradiction. Missing support is not a contradiction. A statement that strong evidence is unavailable uses explicit_lack_of_evidence and relation not_established; it does not contradict the empirical claim. An exhaustive statement that no matching case exists may use explicit_exhaustive_absence.

Support requires complete coverage and every condition matched. Same-scope contradiction requires complete coverage and at least one condition marked contradicted_same_scope. Otherwise use not_established with an unresolved condition. Cite only candidate IDs from that tier: never copy an ID from another intent or tier. Every ID used by a condition must also appear in that judgment's cited_evidence_ids, including evidence used to explain a mismatch. Do not use outside knowledge, infer from omitted excerpts, inspect files, or call tools.

Return every input intent in input order and exactly one judgment for each of single, double, and four. Keep rationales brief and evidence-specific. The application will derive the final three-way verdict after validating this response.

INPUT:
"""


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def strict_output_schema() -> dict:
    """Adapt Pydantic's validation schema to strict structured-output rules."""

    schema = AssessmentBatch.model_json_schema()

    def require_all(value):
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                value["required"] = list(properties)
            for child in value.values():
                require_all(child)
        elif isinstance(value, list):
            for child in value:
                require_all(child)

    require_all(schema)
    return schema


def prepare(input_dir: Path, output_dir: Path) -> None:
    inputs = sorted(input_dir.glob("*.json"))
    if not inputs:
        raise SystemExit("No JSON input packages found.")
    schema_path = output_dir / "semantic-assessment-v2.schema.json"
    write(schema_path, strict_output_schema())
    manifest = {
        "contract_version": "semantic-assessment-v2",
        "promotion_eligible": False,
        "retrieval_mutated": False,
        "schema_sha256": file_hash(schema_path),
        "papers": [],
    }
    for path in inputs:
        package = read(path)
        identifiers = [item["intent_id"] for item in package["intents"]]
        if len(identifiers) != len(set(identifiers)):
            raise SystemExit(f"Duplicate intent in {path}")
        prompt = PROMPT + json.dumps(package, ensure_ascii=False, separators=(",", ":"))
        prompt_path = output_dir / "prompts" / f"{path.stem}.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        manifest["papers"].append(
            {
                "paper_id": package["paper_id"],
                "input": str(path),
                "input_sha256": file_hash(path),
                "prompt": str(prompt_path),
                "prompt_sha256": file_hash(prompt_path),
                "intents": identifiers,
            }
        )
    write(output_dir / "manifest.json", manifest)


def evidence_for(input_item: dict, tier: str) -> dict[str, int]:
    evidence_set = next(item for item in input_item["evidence_sets"] if item["tier"] == tier)
    return {item["candidate_id"]: len(item["excerpt"]) for item in evidence_set["evidence"]}


def validate(input_dir: Path, output_dir: Path, merged_path: Path) -> dict:
    merged = {}
    errors = []
    for input_path in sorted(input_dir.glob("*.json")):
        source = read(input_path)
        result_path = output_dir / f"{input_path.stem}.json"
        raw = read(result_path)
        if set(raw) != {"contract_version", "intents"}:
            errors.append({"file": str(result_path), "error": "invalid_batch_fields"})
            continue
        if raw["contract_version"] != "semantic-assessment-v2":
            errors.append({"file": str(result_path), "error": "invalid_contract_version"})
            continue
        source_ids = [item["intent_id"] for item in source["intents"]]
        result_ids = [item.get("intent_id") for item in raw.get("intents", [])]
        if result_ids != source_ids:
            errors.append({"file": str(result_path), "error": "intent_order_or_coverage"})
            continue
        inputs = {item["intent_id"]: item for item in source["intents"]}
        for raw_item in raw["intents"]:
            intent_id = raw_item["intent_id"]
            judgments = raw_item.get("judgments", [])
            if set(raw_item) != {"intent_id", "judgments"}:
                errors.append(
                    {
                        "file": str(result_path),
                        "intent_id": intent_id,
                        "error": "invalid_intent_fields",
                    }
                )
                continue
            tiers = [item.get("tier") for item in judgments]
            if len(tiers) != 3 or set(tiers) != set(TIERS):
                errors.append(
                    {"file": str(result_path), "intent_id": intent_id, "error": "invalid_tiers"}
                )
                continue
            parsed = []
            for raw_judgment in judgments:
                tier = raw_judgment.get("tier")
                try:
                    judgment = TierAssessment.model_validate(raw_judgment)
                    candidates = evidence_for(inputs[intent_id], judgment.tier)
                    validate_evidence_budget(judgment, candidates)
                    parsed.append(judgment)
                except ValidationError as exc:
                    errors.append(
                        {
                            "file": str(result_path),
                            "intent_id": intent_id,
                            "tier": tier,
                            "error": "invalid_semantic_assessment",
                            "details": [item["msg"] for item in exc.errors(include_url=False)],
                        }
                    )
                except FabricError as exc:
                    errors.append(
                        {
                            "file": str(result_path),
                            "intent_id": intent_id,
                            "tier": tier,
                            "error": exc.code,
                            "details": [exc.message],
                        }
                    )
            if len(parsed) != 3:
                continue
            merged[intent_id] = {}
            for judgment in parsed:
                payload = judgment.model_dump(mode="json")
                payload["verdict"] = semantic_verdict(judgment)
                merged[intent_id][judgment.tier] = payload
    if errors:
        invalid_path = merged_path.with_name(merged_path.stem + "-invalid" + merged_path.suffix)
        write(invalid_path, {"kind": "semantic-assessment-v2-invalid", "errors": errors})
        raise SystemExit(f"Rejected {len(errors)} invalid semantic judgments; see {invalid_path}")
    write(
        merged_path,
        {
            "kind": "semantic-assessment-v2-validated",
            "contract_version": "semantic-assessment-v2",
            "intents": merged,
        },
    )
    return merged


def ratio(numerator: int, denominator: int) -> dict[str, int]:
    return {"numerator": numerator, "denominator": denominator}


def score(merged_path: Path, gold_path: Path, control_scores_path: Path, output: Path) -> dict:
    merged = read(merged_path)["intents"]
    gold = {item["intent_id"]: item for item in read(gold_path)["cases"]}
    complete = {
        (row["intent_id"], row["tier"]): row["selector_complete"]
        for row in read(control_scores_path)["rows"]
    }
    if set(merged) != set(gold):
        raise SystemExit("Assessment and gold intent sets differ.")

    rows = []
    summaries = {}
    for tier in TIERS:
        tier_rows = []
        for intent_id, reference in gold.items():
            judgment = merged[intent_id][tier]
            predicted = judgment["verdict"]
            expected = (
                "insufficient_evidence"
                if reference["reference_verdict"] == "insufficient"
                else reference["reference_verdict"]
            )
            classification_correct = predicted == expected
            answerable = expected != "insufficient_evidence"
            selector_complete = complete[(intent_id, tier)]
            row = {
                "intent_id": intent_id,
                "tier": tier,
                "reference_verdict": reference["reference_verdict"],
                "verdict": predicted,
                "coverage": judgment["coverage"],
                "relation": judgment["relation"],
                "absence_basis": judgment["absence_basis"],
                "cited_evidence_ids": judgment["cited_evidence_ids"],
                "classification_correct": classification_correct,
                "selector_complete": selector_complete,
                "end_to_end_correct": answerable and classification_correct and selector_complete,
                "unsupported_certainty": not answerable and predicted != "insufficient_evidence",
            }
            rows.append(row)
            tier_rows.append(row)
        summaries[tier] = {
            "classification": ratio(
                sum(row["classification_correct"] for row in tier_rows), len(tier_rows)
            ),
            "supported": ratio(
                sum(
                    row["classification_correct"]
                    for row in tier_rows
                    if row["reference_verdict"] == "supported"
                ),
                sum(row["reference_verdict"] == "supported" for row in tier_rows),
            ),
            "contradicted": ratio(
                sum(
                    row["classification_correct"]
                    for row in tier_rows
                    if row["reference_verdict"] == "contradicted"
                ),
                sum(row["reference_verdict"] == "contradicted" for row in tier_rows),
            ),
            "insufficient": ratio(
                sum(
                    row["classification_correct"]
                    for row in tier_rows
                    if row["reference_verdict"] == "insufficient"
                ),
                sum(row["reference_verdict"] == "insufficient" for row in tier_rows),
            ),
            "answerable_end_to_end": ratio(
                sum(row["end_to_end_correct"] for row in tier_rows),
                sum(row["reference_verdict"] != "insufficient" for row in tier_rows),
            ),
            "unsupported_certainty": ratio(
                sum(row["unsupported_certainty"] for row in tier_rows),
                sum(row["reference_verdict"] == "insufficient" for row in tier_rows),
            ),
        }
    result = {
        "kind": "semantic-assessment-v2-development-scores",
        "promotion_eligible": False,
        "tiers": summaries,
        "rows": rows,
    }
    write(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--input-dir", type=Path, required=True)
    prepare_parser.add_argument("--output-dir", type=Path, required=True)
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--input-dir", type=Path, required=True)
    validate_parser.add_argument("--output-dir", type=Path, required=True)
    validate_parser.add_argument("--merged", type=Path, required=True)
    score_parser = commands.add_parser("score")
    score_parser.add_argument("--merged", type=Path, required=True)
    score_parser.add_argument("--gold", type=Path, required=True)
    score_parser.add_argument("--control-scores", type=Path, required=True)
    score_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.input_dir, args.output_dir)
    elif args.command == "validate":
        validate(args.input_dir, args.output_dir, args.merged)
    else:
        score(args.merged, args.gold, args.control_scores, args.output)


if __name__ == "__main__":
    main()
