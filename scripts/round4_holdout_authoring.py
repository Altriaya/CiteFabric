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
from collections import Counter
from pathlib import Path

from citefabric import CiteFabricClient, Config

REFERENCE_HEADING = re.compile(
    r"(?im)^\s*(?:\d+[.)]?\s*)?(?:references|bibliography|literature cited|参考文献)\s*$"
)
REFERENCE_ENTRY = re.compile(
    r"(?i)^\s*(?:\[?\d{1,3}[\].)]|[A-Z][\w'-]+,\s*(?:[A-Z]\.?\s*){1,4}).{0,220}"
    r"(?:19|20)\d{2}[a-z]?(?:[.,;)]|\s)"
)
REFERENCE_MARKERS = re.compile(r"(?i)\b(?:doi:|https?://|arxiv:|et al\.)\b")


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


def bibliography_start(text: str) -> int | None:
    """Return the first bibliography heading offset, if this page contains one."""

    match = REFERENCE_HEADING.search(text)
    return match.start() if match else None


def bibliography_like(text: str) -> bool:
    """Conservatively identify standalone citation entries, not prose with citations."""

    compact = " ".join(text.split())
    return bool(REFERENCE_ENTRY.match(compact)) and bool(REFERENCE_MARKERS.search(compact))


def candidate_stratum(text: str) -> str:
    lowered = text.casefold()
    if re.search(
        r"\b(?:table|figure|fig\.?|accuracy|score|error|rate|mean|median)\b", lowered
    ) or re.search(r"\b\d+(?:\.\d+)?\s*(?:%|ms|s|mb|gb|m|k|b|hz|km|days?|years?)?\b", lowered):
        return "material"
    if re.search(
        r"\b(?:however|although|only|except|unless|limitation|limited|condition|whereas|"
        r"subject to|restricted|cannot|does not|did not|future work)\b",
        lowered,
    ):
        return "scope_condition"
    return "narrative"


def select_candidates(candidates: list[dict], limit: int, *, stratified: bool) -> list[dict]:
    candidates.sort(key=lambda item: (item["score"], -item["page"], -item["start"]), reverse=True)
    if not stratified:
        selected, pages = [], set()
        for item in candidates:
            if item["page"] not in pages:
                selected.append(item)
                pages.add(item["page"])
            if len(selected) == limit:
                return selected
        return (
            selected
            + [item for item in candidates if item not in selected][: limit - len(selected)]
        )

    buckets = {
        name: [item for item in candidates if item["stratum"] == name]
        for name in ("narrative", "material", "scope_condition")
    }
    selected, pages = [], set()
    # Round-robin strata and prefer new pages. Sparse strata fall back to the global pool.
    while len(selected) < limit and any(buckets.values()):
        progress = False
        for name in ("narrative", "material", "scope_condition"):
            bucket = buckets[name]
            if not bucket:
                continue
            position = next(
                (index for index, item in enumerate(bucket) if item["page"] not in pages), 0
            )
            item = bucket.pop(position)
            selected.append(item)
            pages.add(item["page"])
            progress = True
            if len(selected) == limit:
                break
        if not progress:
            break
    return selected


async def build(
    input_dir: Path,
    workspace: Path,
    output: Path,
    *,
    candidates_per_paper: int = 10,
    promotion_profile: bool = False,
):
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
            rejected = Counter()
            in_bibliography = False
            for unit_index, unit in enumerate(snapshot.text_units):
                heading_offset = bibliography_start(unit.text)
                for start, end, quote in sentences(unit.text):
                    if in_bibliography or (heading_offset is not None and start >= heading_offset):
                        rejected["bibliography_section"] += 1
                        continue
                    if bibliography_like(quote):
                        rejected["bibliography_entry"] += 1
                        continue
                    candidates.append(
                        {
                            "unit_index": unit_index,
                            "page": unit.page,
                            "start": start,
                            "end": end,
                            "quote": quote,
                            "score": score(quote),
                            "stratum": candidate_stratum(quote),
                        }
                    )
                if heading_offset is not None:
                    in_bibliography = True
            selected = select_candidates(
                candidates, candidates_per_paper, stratified=promotion_profile
            )
            papers.append(
                {
                    "paper_id": path.stem,
                    "filename": path.name,
                    "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "extraction_id": snapshot.extraction_id,
                    "extraction_text_sha256": snapshot.text_hash,
                    "candidate_profile": "promotion_stratified"
                    if promotion_profile
                    else "page_diverse",
                    "required_intent_quota": {
                        "supported": 4,
                        "contradicted": 3,
                        "insufficient": 3,
                    }
                    if promotion_profile
                    else None,
                    "candidate_strata": dict(Counter(item["stratum"] for item in selected)),
                    "rejected": dict(sorted(rejected.items())),
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
                "promotion_profile": promotion_profile,
                "candidate_filter": "bibliography-section-and-entry-v1",
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
    parser.add_argument("--candidates-per-paper", type=int, default=10)
    parser.add_argument("--profile", choices=("standard", "promotion"), default="standard")
    args = parser.parse_args()
    if not 10 <= args.candidates_per_paper <= 60:
        parser.error("--candidates-per-paper must be between 10 and 60")
    asyncio.run(
        build(
            args.input_dir,
            args.workspace,
            args.output,
            candidates_per_paper=args.candidates_per_paper,
            promotion_profile=args.profile == "promotion",
        )
    )


if __name__ == "__main__":
    main()
