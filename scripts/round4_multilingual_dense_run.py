"""Run gold-blind lexical and local multilingual dense candidate retrieval.

Requires the optional experiment dependency ``sentence-transformers``. The
model is downloaded once, then all paper/query inference is local.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from citefabric.retrieval import concept_coverage, query_plan
from citefabric.storage import Store


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def compact(row: dict, rank: int, score: float) -> dict:
    return {
        "passage_id": row["id"],
        "extraction_id": row["extraction_id"],
        "unit_id": row["unit_id"],
        "start": row["start"],
        "end": row["end"],
        "rank": rank,
        "score": score,
    }


def rrf(lexical: list[dict], dense: list[dict]) -> list[dict]:
    combined: dict[str, dict] = {}
    for source, rows in (("lexical", lexical), ("dense", dense)):
        for rank, row in enumerate(rows, 1):
            item = combined.setdefault(row["id"], {"row": row, "ranks": {}})
            item["ranks"][source] = rank
    ranked = sorted(
        combined.values(),
        key=lambda item: (
            -sum(1 / (60 + rank) for rank in item["ranks"].values()),
            item["row"]["id"],
        ),
    )
    return [item["row"] for item in ranked]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="intfloat/multilingual-e5-small")
    parser.add_argument("--limit", type=int, default=48)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Output already exists")
    prepared = read(args.prepared / "prepared.json")
    queries = read(args.prepared / "queries.json")
    model = SentenceTransformer(args.model)
    store = Store(args.prepared / "workspaces" / "v2")
    rows_out = []
    started = time.perf_counter()
    try:
        by_paper = {paper["paper_id"]: paper for paper in queries["papers"]}
        for paper_id in by_paper:
            edition_id = prepared["policies"]["v2"][paper_id]["selector"]["edition_id"]
            passages = [
                dict(row)
                for row in store.db.execute(
                    "SELECT * FROM passages WHERE edition_id=? ORDER BY unit_id,start,id",
                    (edition_id,),
                )
            ]
            passage_vectors = model.encode(
                ["passage: " + row["text"] for row in passages],
                batch_size=32,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            intents = [intent for intent in queries["intents"] if intent["paper_id"] == paper_id]
            for language in ("en", "zh"):
                query_vectors = model.encode(
                    ["query: " + intent["query"][language] for intent in intents],
                    batch_size=32,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                for intent, query_vector in zip(intents, query_vectors, strict=True):
                    query = intent["query"][language]
                    plan = query_plan(query, True)
                    lexical = store.passage_search([edition_id], plan["expanded"], limit=args.limit)
                    if plan["mappings"]:
                        lexical.sort(
                            key=lambda row: (
                                -concept_coverage(row["text"], plan),
                                row["score"],
                                row["id"],
                            )
                        )
                    similarities = np.asarray(passage_vectors) @ np.asarray(query_vector)
                    order = np.argsort(-similarities, kind="stable")[: args.limit]
                    dense = [passages[int(index)] for index in order]
                    hybrid = rrf(lexical, dense)[: args.limit]
                    arms = {
                        "lexical_v2_candidates": lexical,
                        "multilingual_e5_candidates": dense,
                        "lexical_dense_rrf_candidates": hybrid,
                    }
                    rows_out.append(
                        {
                            "intent_id": intent["intent_id"],
                            "paper_id": paper_id,
                            "language": language,
                            "query": query,
                            "query_plan": plan,
                            "arms": {
                                arm: [
                                    compact(
                                        row,
                                        rank,
                                        float(similarities[passages.index(row)])
                                        if arm == "multilingual_e5_candidates"
                                        else 1 / rank,
                                    )
                                    for rank, row in enumerate(values, 1)
                                ]
                                for arm, values in arms.items()
                            },
                        }
                    )
    finally:
        store.close()
    output = {
        "kind": "round4_multilingual_dense_run",
        "gold_access": "No gold path or gold file opened by this process.",
        "model": args.model,
        "embedding_dimension": model.get_embedding_dimension(),
        "max_sequence_length": model.max_seq_length,
        "candidate_limit": args.limit,
        "runtime_seconds": time.perf_counter() - started,
        "environment": {
            "python": platform.python_version(),
            "sentence_transformers": version("sentence-transformers"),
            "numpy": version("numpy"),
        },
        "rows": rows_out,
    }
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
