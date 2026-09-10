"""Run an offline synthetic contract demo, NOT a blind pilot or quality benchmark."""

from __future__ import annotations

import argparse
import asyncio
import copy
from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

try:
    from scripts import round4_eval as ev
except ModuleNotFoundError:
    import round4_eval as ev


def pdf_bytes(text):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    content.set_data(("BT /F1 10 Tf 30 700 Td (" + text + ") Tj ET").encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def make_queries(directory):
    directory.mkdir(parents=True, exist_ok=False)
    review = {
        "author_id": "synthetic-generator",
        "reviewer_ids": [],
        "independence": "self_review",
        "saw_retrieval_outputs": False,
        "adjudication": "Synthetic contract only; not human or independent annotation.",
    }
    papers, intents = [], []
    for n in range(2):
        key = f"synthetic{n}"
        raw = pdf_bytes(f"Memory{n} improved accuracy to 42 percent. Only adults were evaluated.")
        (directory / f"{key}.pdf").write_bytes(raw)
        papers.append(
            {
                "paper_id": key,
                "family_id": key,
                "title": f"Synthetic contract {n}",
                "domain": f"synthetic-domain{n}",
                "source_url": "https://example.org/synthetic.pdf",
                "filename": f"{key}.pdf",
                "sha256": ev.digest(raw),
                "pages": 1,
                "edition_label": "synthetic-v1",
                "metadata_basis": "Generated test PDF; no real paper",
                "layer": "core",
                "challenges": ["narrative"],
            }
        )
        for kind in ("supported", "contradicted", "insufficient"):
            unknown = kind == "insufficient"
            query = {
                "en": "UnreportedZZZ" if unknown else f"Memory{n} accuracy adults",
                "zh": "未报告UnreportedZZZ" if unknown else f"Memory{n}准确率与成人范围",
            }
            intents.append(
                {
                    "intent_id": f"{key}-{kind}",
                    "parent_intent_id": None,
                    "paper_id": key,
                    "query": query,
                    "claim": {"en": "Synthetic claim " + kind, "zh": "合成论断 " + kind},
                    "equivalence_review": copy.deepcopy(review),
                }
            )
    variant = copy.deepcopy(intents[0])
    variant.update(intent_id="synthetic-variant", parent_intent_id=intents[0]["intent_id"])
    intents.append(variant)
    queries = {
        "schema_version": "round4-0.1",
        "kind": "queries",
        "protocol_version": "0.1-draft",
        "cohort_id": "synthetic-contract",
        "split": "pilot",
        "status": "draft",
        "papers": papers,
        "intents": intents,
    }
    ev.write(directory / "queries.json", queries)
    return queries


def make_gold(queries_path, preparation):
    queries = ev.read(queries_path)
    papers = {p["paper_id"]: p for p in queries["papers"]}
    cases = []
    for intent in queries["intents"]:
        verdict = "supported" if intent["parent_intent_id"] else intent["intent_id"].split("-")[-1]
        snapshot = preparation["snapshots"][intent["paper_id"]]
        text = snapshot["text_units"][0]["text"]
        absent = verdict == "insufficient"
        cases.append(
            {
                "intent_id": intent["intent_id"],
                "paper_id": intent["paper_id"],
                "source_sha256": papers[intent["paper_id"]]["sha256"],
                "extraction_text_sha256": snapshot["text_hash"].removeprefix("sha256:"),
                "reference_verdict": verdict,
                "rationale": "Synthetic oracle verifies tooling only, not scientific evidence quality.",
                "tags": ["unreported_configuration", "condition_counterexample"]
                if absent
                else ["scope_limitation"],
                "spans": []
                if absent
                else [
                    {
                        "span_id": "s1",
                        "unit_index": 0,
                        "page": 1,
                        "start": 0,
                        "end": len(text),
                        "quote": text,
                        "role": "limitation",
                    }
                ],
                "requirements": []
                if absent
                else [
                    {
                        "requirement_id": "r1",
                        "dimension": "scope",
                        "description": "Synthetic complete sentence and adult qualifier",
                        "span_ids": ["s1"],
                        "visual_requirements": [],
                        "relation": "Same explicitly named method",
                        "derivation": None,
                    }
                ],
                "sufficient_sets": [] if absent else [["r1"]],
                "absence_review": {
                    "sections_reviewed": ["Entire one-page synthetic PDF"],
                    "terms_searched": ["UnreportedZZZ"],
                    "missing_conditions": "Unreported synthetic configuration",
                    "limitations": "Synthetic only",
                }
                if absent
                else None,
                "review": copy.deepcopy(intent["equivalence_review"]),
            }
        )
    return {
        "schema_version": "round4-0.1",
        "kind": "gold",
        "protocol_version": queries["protocol_version"],
        "cohort_id": queries["cohort_id"],
        "queries_sha256": ev.digest(queries_path.read_bytes()),
        "cases": cases,
    }


def synthetic_ratings(template, package, gold, reviewer_id):
    review = copy.deepcopy(template)
    review["reviewer_id"] = reviewer_id
    items = {i["item_id"]: i for i in package["items"]}
    cases = {c["intent_id"]: c for c in gold["cases"]}
    for rating in review["ratings"]:
        item = items[rating["item_id"]]
        case = cases[item["intent_id"]]
        absent = case["reference_verdict"] == "insufficient"
        present = any(
            "Only adults were evaluated." in e["excerpt"] and "42 percent" in e["excerpt"]
            for e in item["evidence"]
        )
        rating.update(
            sufficiency="not_applicable" if absent else "complete" if present else "none",
            requirements={} if absent else {"r1": "present" if present else "missing"},
            harmful_mismatch=False,
            mismatch_types=[],
            limitation_preserved=None if absent else present,
            failure_stage="none" if present or absent else "selection",
            evidence_aliases=[e["alias"] for e in item["evidence"]] if present else [],
            rationale="SYNTHETIC ORACLE: two copies exercise review merging, not independent human ratings.",
        )
    return review


async def demo(output_dir):
    output_dir.mkdir(parents=True, exist_ok=False)
    make_queries(output_dir / "input")
    prepared = output_dir / "prepared"
    preparation = await ev.prepare(
        output_dir / "input/queries.json", output_dir / "input", prepared
    )
    gold = make_gold(prepared / "queries.json", preparation)
    gold_path = output_dir / "gold.json"
    ev.write(gold_path, gold)
    ev.validate_gold(prepared / "queries.json", gold, preparation["snapshots"])
    # These are closed synthetic answers, created before any retrieval.
    run_dir = output_dir / "run"
    await ev.run(prepared, run_dir)
    package = ev.blind(run_dir, output_dir / "review", output_dir / "private-key.json")
    template = ev.read(output_dir / "review/rating-template.json")
    paths = []
    for label in ("a", "b"):
        path = output_dir / f"synthetic-review-{label}.json"
        ev.write(path, synthetic_ratings(template, package, gold, f"synthetic-oracle-{label}"))
        paths.append(path)
    report = ev.score(
        run_dir,
        output_dir / "review/items.json",
        output_dir / "private-key.json",
        gold_path,
        paths,
        output_dir / "scores.json",
    )
    ev.write(
        output_dir / "DEMO-NOT-BENCHMARK.json",
        {
            "mode": "synthetic_contract_smoke",
            "independent_human_review": False,
            "promotion_eligible": False,
            "real_papers": 0,
            "independent_intents": 6,
            "variants": 1,
            "queries": 112,
            "report": "scores.json",
        },
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    result = asyncio.run(demo(parser.parse_args().output_dir))
    print(
        "Synthetic contract complete; no real-paper or independent blind evidence. Promotion: "
        + result["promotion"]["status"]
    )
