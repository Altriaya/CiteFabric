"""Run a bounded GPT-5.5 verifier pilot over frozen opened-development evidence.

Gold labels are applied only after all CiteFabric verification calls finish. This
runner is for prompt and integration debugging; its results are never promotion eligible.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from citefabric import CiteFabricClient, Config
from citefabric.openai_verifier import PRICING_VERSION, PROMPT_VERSION, prompt_hash

DEFAULT_CASES = ("Q01", "Q20", "Q23", "Q30", "Q31", "Q35")
EXPECTED_TO_PUBLIC = {
    "supported": "supported",
    "contradicted": "contradicted",
    "insufficient": "insufficient_evidence",
}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def value_hash(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def selected_cases(args, benchmark: dict) -> list[dict]:
    cases = benchmark["cases"]
    by_id = {case["id"]: case for case in cases}
    requested = [case["id"] for case in cases] if args.all else args.case or list(DEFAULT_CASES)
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise SystemExit("Unknown case IDs: " + ", ".join(unknown))
    if len(requested) != len(set(requested)):
        raise SystemExit("Case IDs must be unique.")
    return [by_id[identifier] for identifier in requested]


def frozen_case(case: dict, evidence_dir: Path) -> dict:
    path = evidence_dir / f"{case['id']}.json"
    if not path.is_file():
        raise SystemExit(f"Missing frozen evidence package: {path}")
    package = read(path)
    if package.get("case_id") != case["id"]:
        raise SystemExit(f"Case ID mismatch in {path}")
    hits = package.get("retrieval", {}).get("data", {}).get("hits", [])
    if not hits:
        return {
            "case_id": case["id"],
            "claim": case["claim_zh"],
            "evidence_status": "no_frozen_evidence",
            "evidence_ids": [],
            "evidence_bundle_hash": value_hash([]),
            "source_file": str(path),
            "source_file_hash": file_hash(path),
        }
    evidence = [hit["evidence"] for hit in hits]
    edition_ids = {item["edition_id"] for item in evidence}
    fabric_ids = {item["fabric_id"] for item in evidence}
    if len(edition_ids) != 1 or len(fabric_ids) != 1:
        raise SystemExit(f"Evidence package is not scoped to one edition: {path}")
    evidence_ids = [item["evidence_id"] for item in evidence]
    if len(evidence_ids) > 6 or sum(len(item["excerpt"]) for item in evidence) > 6000:
        raise SystemExit(f"Evidence package exceeds verifier budget: {path}")
    return {
        "case_id": case["id"],
        "claim": case["claim_zh"],
        "evidence_status": "available",
        "paper": {"ref": fabric_ids.pop(), "edition_id": edition_ids.pop()},
        "evidence_ids": evidence_ids,
        "evidence_bundle_hash": value_hash(evidence),
        "source_file": str(path),
        "source_file_hash": file_hash(path),
    }


def base_report(args, frozen: list[dict]) -> dict:
    return {
        "kind": "citefabric_openai_verifier_opened_dev_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "promotion_eligible": False,
        "gold_visible_to_model": False,
        "benchmark": str(args.benchmark),
        "benchmark_hash": file_hash(args.benchmark),
        "evidence_dir": str(args.evidence_dir),
        "data_dir": str(args.data_dir),
        "provider": "openai",
        "model": args.model,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": prompt_hash(),
        "pricing_version": PRICING_VERSION,
        "reasoning_effort": args.reasoning_effort,
        "cases": frozen,
    }


async def run(args) -> None:
    benchmark = read(args.benchmark)
    cases = selected_cases(args, benchmark)
    frozen = [frozen_case(case, args.evidence_dir) for case in cases]
    report = base_report(args, frozen)
    if args.preflight:
        config = Config.load(data_dir=args.data_dir, offline=True, verifier_provider="none")
        async with CiteFabricClient(config) as client:
            for item in frozen:
                for evidence_id in item["evidence_ids"]:
                    stored = client.store.evidence(evidence_id)
                    if stored.edition_id != item["paper"]["edition_id"]:
                        raise SystemExit(f"Stored evidence edition mismatch: {evidence_id}")
        report["status"] = "preflight_ok"
        report["live_requests_made"] = 0
    else:
        config = Config.load(
            data_dir=args.data_dir,
            offline=True,
            verifier_provider="openai",
            verifier_model=args.model,
            verifier_reasoning_effort=args.reasoning_effort,
        )
        if config.openai_api_key is None:
            raise SystemExit(
                "No OpenAI API key configured. Set CITEFABRIC_OPENAI_API_KEY or OPENAI_API_KEY."
            )
        results = []
        requests_made = 0
        async with CiteFabricClient(config) as client:
            for item in frozen:
                if item["evidence_status"] != "available":
                    results.append(
                        {
                            "case_id": item["case_id"],
                            "actual_verdict": "unavailable",
                            "result_status": "not_run_no_evidence",
                            "outcomes": [],
                            "receipt": None,
                        }
                    )
                    continue
                requests_made += 1
                verified = await client.verify_claim(
                    item["claim"],
                    [item["paper"]],
                    evidence_ids=item["evidence_ids"],
                )
                receipts = (verified.data or {}).get("receipts", [])
                receipt = receipts[0] if receipts else None
                assessment = receipt["assessment"] if receipt else None
                actual = assessment["verdict"] if assessment else "unavailable"
                results.append(
                    {
                        "case_id": item["case_id"],
                        "actual_verdict": actual,
                        "result_status": verified.status,
                        "outcomes": [value.model_dump(mode="json") for value in verified.outcomes],
                        "receipt": receipt,
                    }
                )
        gold = {case["id"]: case["expected_verdict"] for case in cases}
        for item in results:
            expected = EXPECTED_TO_PUBLIC[gold[item["case_id"]]]
            item["expected_verdict"] = expected
            item["correct"] = item["actual_verdict"] == expected
        completed = [item for item in results if item["actual_verdict"] != "unavailable"]
        correct = sum(item["correct"] for item in completed)
        costs = [
            item["receipt"]["assessment"]["usage"].get("cost")
            for item in completed
            if item["receipt"]["assessment"]["usage"].get("cost") is not None
        ]
        report.update(
            status="completed" if len(completed) == len(results) else "partial",
            live_requests_made=requests_made,
            summary={
                "selected": len(results),
                "verifier_requests": requests_made,
                "completed": len(completed),
                "correct": correct,
                "accuracy_on_completed": correct / len(completed) if completed else None,
                "cost_usd": round(sum(costs), 8) if costs else None,
            },
            results=results,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: report[key] for key in ("status", "live_requests_made")}, ensure_ascii=False
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(".citefabric/offline_round2_zh_v4"))
    parser.add_argument("--benchmark", type=Path, default=Path("benchmarks/round2.json"))
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("output/validation/offline_round2_zh_v4_20260921"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("output/verifier/openai_dev_pilot.json")
    )
    parser.add_argument("--model", default="gpt-5.5-2026-04-23")
    parser.add_argument(
        "--reasoning-effort", choices=("none", "low", "medium", "high", "xhigh"), default="medium"
    )
    parser.add_argument("--case", action="append", help="Case ID; repeat to select several.")
    parser.add_argument("--all", action="store_true", help="Run all 38 opened-development cases.")
    parser.add_argument(
        "--preflight", action="store_true", help="Validate and hash inputs without API calls."
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
