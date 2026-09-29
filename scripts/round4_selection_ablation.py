"""Opened-data, gold-blind lexical window selection ablation for Round 4.

The selector sees only a query and existing top-48 passage candidates. Gold is
read after selection for coordinate-proxy diagnostics. This does not change the
product retrieval policy or provide a semantic sufficiency verdict.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

from round4_translation_diagnostic import gold_proxy

from citefabric.retrieval import query_plan
from citefabric.storage import Store

STOP = set(
    "the a an of in on for with to and or is are was were do does did this that "
    "paper study what which how where who why results result report reported show "
    "using used use from its their at by as if than then".split()
)
WINDOW = 950
STRIDE = 450


def terms(text: str) -> list[str]:
    return [
        x for x in re.findall(r"[a-z][a-z0-9]*|\d+(?:\.\d+)?", text.casefold()) if x not in STOP
    ]


def windows(rows: list[dict], query: str) -> list[dict]:
    query_terms = list(dict.fromkeys(terms(query)))
    original_terms = terms(query)
    pairs = set(zip(original_terms, original_terms[1:], strict=False))
    document_frequency = Counter()
    for row in rows:
        document_frequency.update(set(terms(row["text"])))
    weights = {
        word: math.log((len(rows) + 1) / (document_frequency[word] + 1)) + 1 for word in query_terms
    }
    found: dict[tuple[str, int, int], dict] = {}
    for rank, row in enumerate(rows, 1):
        length = len(row["text"])
        starts = {0, max(0, length - WINDOW)}
        starts.update(range(0, max(1, length - WINDOW + 1), STRIDE))
        for local_start in starts:
            local_end = min(length, local_start + WINDOW)
            excerpt = row["text"][local_start:local_end]
            present = set(terms(excerpt))
            sequence = terms(excerpt)
            adjacent = set(zip(sequence, sequence[1:], strict=False))
            coverage = sum(weights[word] for word in query_terms if word in present)
            phrase = sum(min(weights[a], weights[b]) for a, b in pairs if (a, b) in adjacent)
            page = int(row["unit_id"].split(":", 1)[1])
            first_pages = 0.6 if page <= 2 else 0.0
            score = coverage + 0.7 * phrase + first_pages + 1.0 / (rank + 2)
            candidate = {
                "unit_id": row["unit_id"],
                "start": row["start"] + local_start,
                "end": row["start"] + local_end,
                "text": excerpt,
                "score": score,
                "query_terms": sorted(present & set(query_terms)),
                "rank": rank,
            }
            found[(candidate["unit_id"], candidate["start"], candidate["end"])] = candidate
    return list(found.values())


def select(rows: list[dict], query: str) -> list[dict]:
    pool = windows(rows, query)
    selected: list[dict] = []
    while pool and len(selected) < 6:

        def adjusted(candidate: dict) -> tuple:
            same_page = sum(x["unit_id"] == candidate["unit_id"] for x in selected)
            overlap = sum(
                max(0, min(candidate["end"], x["end"]) - max(candidate["start"], x["start"]))
                / WINDOW
                for x in selected
                if x["unit_id"] == candidate["unit_id"]
            )
            shared = max(
                (
                    len(set(candidate["query_terms"]) & set(x["query_terms"]))
                    / max(1, len(set(candidate["query_terms"]) | set(x["query_terms"])))
                    for x in selected
                ),
                default=0.0,
            )
            return (
                candidate["score"] - 1.2 * same_page - 3.0 * overlap - 1.0 * shared,
                -candidate["rank"],
                candidate["unit_id"],
                candidate["start"],
            )

        best = max(pool, key=adjusted)
        pool.remove(best)
        if any(
            x["unit_id"] == best["unit_id"]
            and best["start"] < x["end"]
            and x["start"] < best["end"]
            for x in selected
        ):
            continue
        if sum(len(x["text"]) for x in selected) + len(best["text"]) > 6000:
            continue
        selected.append(best)
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--rewrites", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    queries = json.loads((args.base / "queries.json").read_text())
    gold = {x["intent_id"]: x for x in json.loads((args.base / "gold.json").read_text())["cases"]}
    prepared = json.loads((args.base / "prepared" / "prepared.json").read_text())
    rewrites = {x["intent_id"]: x["en"] for x in json.loads(args.rewrites.read_text())["rewrites"]}
    args.output.mkdir(parents=True)
    report = {"kind": "round4_opened_selection_ablation", "rows": []}
    store = Store(args.base / "prepared" / "workspaces" / "v2")
    try:
        for intent in queries["intents"]:
            iid = intent["intent_id"]
            paper = intent["paper_id"]
            edition_id = prepared["policies"]["v2"][paper]["selector"]["edition_id"]
            for arm, query in (
                ("model_en", rewrites[iid]),
                ("reference_en", intent["query"]["en"]),
            ):
                pool = store.passage_search([edition_id], query_plan(query, True)["expanded"])
                chosen = select(pool, query)
                case = gold[iid]
                audit = gold_proxy(case, chosen, evidence=False)
                report["rows"].append(
                    {
                        "intent_id": iid,
                        "paper_id": paper,
                        "arm": arm,
                        "reference_verdict": case["reference_verdict"],
                        "candidate_count": len(pool),
                        "selected_count": len(chosen),
                        "selected_chars": sum(len(x["text"]) for x in chosen),
                        "selected_proxy": audit,
                        "evidence": [
                            {
                                "locator": {
                                    "page": int(x["unit_id"].split(":", 1)[1]),
                                    "text_unit_id": x["unit_id"],
                                    "char_start": x["start"],
                                    "char_end": x["end"],
                                },
                                "excerpt": x["text"],
                            }
                            for x in chosen
                        ],
                    }
                )
    finally:
        store.close()
    (args.output / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    for arm in ("model_en", "reference_en"):
        answerable = [
            x
            for x in report["rows"]
            if x["arm"] == arm and x["reference_verdict"] != "insufficient"
        ]
        print(
            arm,
            sum(x["selected_proxy"]["full_minimal_set"] for x in answerable),
            "/",
            len(answerable),
        )


if __name__ == "__main__":
    main()
