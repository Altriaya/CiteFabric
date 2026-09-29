"""Create a no-retrieval authoring worksheet from frozen local PDFs.

The worksheet is not a benchmark fixture and carries no claim labels.  It makes
candidate spans reviewable against the exact CiteFabric extraction snapshot
before questions and gold are authored and sealed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path

from citefabric import CiteFabricClient, Config


def sentences(text: str):
    for match in re.finditer(r"(?s)(.{80,900}?[.!?](?:\s|$))", text):
        raw = match.group(1)
        value = raw.strip()
        if len(value) >= 100:
            left = len(raw) - len(raw.lstrip())
            right = len(raw) - len(raw.rstrip())
            yield match.start(1) + left, match.end(1) - right, value


def score(text: str) -> tuple[int, int, int]:
    lowered = text.casefold()
    signals = sum(
        word in lowered
        for word in (
            "we introduce",
            "we present",
            "results",
            "accuracy",
            "error",
            "dataset",
            "table",
            "however",
            "limitation",
            "compared",
        )
    )
    numbers = len(re.findall(r"\b\d+(?:\.\d+)?\b", text))
    return signals, numbers, -len(text)


async def build(input_dir: Path, workspace: Path, output: Path):
    if output.exists():
        raise ValueError("Output already exists")
    papers = []
    async with CiteFabricClient(
        Config(data_dir=workspace, offline=True, parse_timeout=60)
    ) as client:
        for path in sorted(input_dir.glob("*.pdf")):
            imported = await client.import_document(path, title=path.stem)
            if not imported.data or not imported.data.get("extraction_id"):
                raise RuntimeError(f"Could not extract {path.name}: {imported.model_dump_json()}")
            snapshot = client.store.extraction(imported.data["extraction_id"])
            candidates = []
            for unit_index, unit in enumerate(snapshot.text_units):
                candidates.extend(
                    {
                        "unit_index": unit_index,
                        "page": unit.page,
                        "start": start,
                        "end": end,
                        "quote": quote,
                        "score": score(quote),
                    }
                    for start, end, quote in sentences(unit.text)
                )
            # One candidate per page first preserves topical diversity; then fill
            # from the highest-scored remaining passages.  It is deterministic.
            candidates.sort(
                key=lambda item: (item["score"], -item["page"], -item["start"]), reverse=True
            )
            selected, pages = [], set()
            for item in candidates:
                if item["page"] not in pages:
                    selected.append(item)
                    pages.add(item["page"])
                if len(selected) == 10:
                    break
            for item in candidates:
                if len(selected) == 10:
                    break
                if item not in selected:
                    selected.append(item)
            papers.append(
                {
                    "paper_id": path.stem,
                    "filename": path.name,
                    "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "extraction_id": snapshot.extraction_id,
                    "extraction_text_sha256": snapshot.text_hash,
                    "candidates": selected,
                }
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "kind": "round4_holdout_authoring_worksheet",
                "status": "needs_human_or_model_authored_queries_and_gold",
                "warning": "Candidates are not labels and must not be supplied to retrieval.",
                "papers": papers,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(build(args.input_dir, args.workspace, args.output))


if __name__ == "__main__":
    main()
