"""Opened Round 4 query-translation diagnostic; never used for promotion scoring.

Replay paired Chinese, query-only English rewrite, and reference English queries
through the unchanged product client. The coordinate audit is deliberately a
strict gold-span proxy, not a semantic evidence-sufficiency rating.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from citefabric.client import CiteFabricClient
from citefabric.config import Config
from citefabric.evidence_selection import candidates, plan_query
from citefabric.retrieval import query_plan


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def covered(span: dict, rows: list[dict], *, evidence: bool) -> bool:
    unit = f"page:{span['page']}"
    for row in rows:
        if evidence:
            loc = row["locator"]
            where = loc["text_unit_id"]
            start, end = loc["char_start"], loc["char_end"]
        else:
            where = row["unit_id"]
            start, end = row["start"], row["end"]
        if where == unit and start <= span["start"] and end >= span["end"]:
            return True
    return False


def gold_proxy(case: dict, rows: list[dict], *, evidence: bool) -> dict:
    spans = {x["span_id"]: x for x in case["spans"]}
    present = {sid for sid, span in spans.items() if covered(span, rows, evidence=evidence)}
    requirements = {
        r["requirement_id"]: bool(r["span_ids"])
        and not r["visual_requirements"]
        and all(sid in present for sid in r["span_ids"])
        for r in case["requirements"]
    }
    return {
        "covered_span_ids": sorted(present),
        "covered_requirement_ids": sorted(k for k, v in requirements.items() if v),
        "full_minimal_set": any(
            all(requirements.get(rid, False) for rid in group) for group in case["sufficient_sets"]
        ),
    }


def candidate_rows(client, policy: str, edition_id: str, query: str, data: dict):
    if (
        policy == "structured_v3"
        and data.get("structure_index_version")
        and (data.get("selection_trace") or {}).get("route") != "lexical_compatibility"
    ):
        ids = data.get("structure_index_ids") or []
        return candidates(client.store, ids, edition_id, plan_query(query, True)) if ids else []
    plan = query_plan(query, True)
    return client.store.passage_search([edition_id], plan["expanded"])


async def replay(base: Path, rewrites_path: Path, output: Path):
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    queries_path = base / "queries.json"
    gold_path = base / "gold.json"
    prep_path = base / "prepared" / "prepared.json"
    q, g, prep = (read(x) for x in (queries_path, gold_path, prep_path))
    translations = read(rewrites_path)["rewrites"]
    intents = q["intents"]
    if [x["intent_id"] for x in translations] != [x["intent_id"] for x in intents]:
        raise ValueError("Rewrite IDs/order differ from frozen opened queries")
    translated = {x["intent_id"]: x["en"] for x in translations}
    cases = {x["intent_id"]: x for x in g["cases"]}
    result = {
        "kind": "round4_opened_translation_diagnostic",
        "limitations": "Direct product-client replay; strict coordinate proxy, not semantic ESR; no independent reviewer.",
        "input_sha256": {
            "queries": sha(queries_path),
            "gold": sha(gold_path),
            "prepared": sha(prep_path),
            "rewrites": sha(rewrites_path),
        },
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "parameters": {
            "max_chars": 6000,
            "max_passages": 6,
            "allow_abstract": False,
            "expand_query": True,
            "include_context": True,
            "offline": True,
            "policies": ["v2", "structured_v3"],
            "arms": ["original_zh", "model_en", "reference_en"],
        },
        "rows": [],
    }
    for policy in result["parameters"]["policies"]:
        workspace = output / "workspaces" / policy
        shutil.copytree(base / "prepared" / "workspaces" / policy, workspace)
        config = Config.load(data_dir=workspace, offline=True)
        async with CiteFabricClient(config) as client:
            for intent in intents:
                iid = intent["intent_id"]
                paper_id = intent["paper_id"]
                selector = prep["policies"][policy][paper_id]["selector"]
                if not selector:
                    raise ValueError(f"Missing imported paper {paper_id}/{policy}")
                for arm, query in (
                    ("original_zh", intent["query"]["zh"]),
                    ("model_en", translated[iid]),
                    ("reference_en", intent["query"]["en"]),
                ):
                    started = time.perf_counter()
                    found = await client.find_evidence(
                        [selector],
                        query,
                        retrieval_policy=policy,
                        max_chars=6000,
                        max_passages=6,
                        allow_abstract=False,
                        expand_query=True,
                        include_context=True,
                    )
                    elapsed = time.perf_counter() - started
                    data = found.data or {}
                    hits = [h["evidence"] for h in data.get("hits", [])]
                    candidates_ = candidate_rows(
                        client, policy, selector["edition_id"], query, data
                    )
                    case = cases[iid]
                    row = {
                        "intent_id": iid,
                        "paper_id": paper_id,
                        "policy": policy,
                        "arm": arm,
                        "query": query,
                        "reference_verdict": case["reference_verdict"],
                        "status": found.status,
                        "elapsed_seconds": elapsed,
                        "candidate_count": len(candidates_),
                        "selected_count": len(hits),
                        "selected_chars": sum(len(h["excerpt"]) for h in hits),
                        "route": (data.get("selection_trace") or {}).get(
                            "route", "structured_or_v2"
                        ),
                        "candidate_proxy": gold_proxy(case, candidates_, evidence=False),
                        "selected_proxy": gold_proxy(case, hits, evidence=True),
                        "evidence": [
                            {
                                "evidence_id": h["evidence_id"],
                                "locator": h["locator"],
                                "excerpt": h["excerpt"],
                            }
                            for h in hits
                        ],
                    }
                    result["rows"].append(row)
                    with (output / "journal.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    (output / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--rewrites", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = asyncio.run(replay(args.base, args.rewrites, args.output))
    for policy in data["parameters"]["policies"]:
        for arm in data["parameters"]["arms"]:
            rows = [
                x
                for x in data["rows"]
                if x["policy"] == policy
                and x["arm"] == arm
                and x["reference_verdict"] != "insufficient"
            ]
            print(
                policy,
                arm,
                "answerable",
                len(rows),
                "candidate_proxy",
                sum(x["candidate_proxy"]["full_minimal_set"] for x in rows),
                "selected_proxy",
                sum(x["selected_proxy"]["full_minimal_set"] for x in rows),
            )


if __name__ == "__main__":
    main()
