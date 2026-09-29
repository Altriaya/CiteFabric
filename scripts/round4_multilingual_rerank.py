"""Gold-blind multilingual cross-encoder reranking of lexical+dense candidates."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sentence_transformers import CrossEncoder

from citefabric.storage import Store


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--candidate-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Output already exists")
    source = read(args.candidate_run)
    model = CrossEncoder(args.model)
    store = Store(args.prepared / "workspaces" / "v2")
    rows = []
    started = time.perf_counter()
    try:
        for source_row in source["rows"]:
            if source_row["language"] != "zh":
                continue
            ids = list(
                dict.fromkeys(
                    item["passage_id"]
                    for arm in (
                        "lexical_v2_candidates",
                        "multilingual_e5_candidates",
                    )
                    for item in source_row["arms"][arm]
                )
            )
            candidates = []
            for passage_id in ids:
                row = store.db.execute(
                    "SELECT * FROM passages WHERE id=?", (passage_id,)
                ).fetchone()
                if row is not None:
                    candidates.append(dict(row))
            scores = model.predict(
                [(source_row["query"], row["text"]) for row in candidates],
                batch_size=32,
                show_progress_bar=False,
            )
            ranked = sorted(
                zip(candidates, scores, strict=True),
                key=lambda pair: (-float(pair[1]), pair[0]["id"]),
            )[:48]
            rows.append(
                {
                    "intent_id": source_row["intent_id"],
                    "paper_id": source_row["paper_id"],
                    "language": "zh",
                    "query": source_row["query"],
                    "arms": {
                        "multilingual_cross_encoder_candidates": [
                            {
                                "passage_id": row["id"],
                                "extraction_id": row["extraction_id"],
                                "unit_id": row["unit_id"],
                                "start": row["start"],
                                "end": row["end"],
                                "rank": rank,
                                "score": float(score),
                            }
                            for rank, (row, score) in enumerate(ranked, 1)
                        ]
                    },
                }
            )
    finally:
        store.close()
    payload = {
        "kind": "round4_multilingual_cross_encoder_run",
        "gold_access": "No gold path or gold file opened by this process.",
        "model": args.model,
        "source_candidate_model": source["model"],
        "max_sequence_length": model.max_seq_length,
        "runtime_seconds": time.perf_counter() - started,
        "rows": rows,
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
