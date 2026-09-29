"""Run the 0.1 discovery-to-citation path against a real arXiv document."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from citefabric import CiteFabricClient, Config


async def run(args):
    ref = "arxiv:1810.04805v2"
    report = {"kind": "citefabric_0.1_online_release_smoke", "paper_ref": ref}
    config = Config.load(data_dir=args.data_dir, offline=False)
    async with CiteFabricClient(config) as client:
        search = await client.search_papers(
            "BERT pre-training deep bidirectional transformers language understanding",
            sources=["arxiv"],
            limit=5,
        )
        assert search.status in {"ok", "partial"}, search.model_dump(mode="json")
        matches = [
            paper
            for paper in search.data["papers"]
            if any(
                identifier["namespace"] == "arxiv"
                and identifier["value"] == "1810.04805"
                and identifier["version"] == "v2"
                for identifier in paper["external_ids"]
            )
        ]
        assert matches, search.model_dump(mode="json")
        report["search"] = {
            "status": search.status,
            "returned": len(search.data["papers"]),
            "matched_fabric_id": matches[0]["fabric_id"],
            "provider_outcomes": [item.model_dump(mode="json") for item in search.outcomes],
        }

        paper = await client.get_paper(ref)
        assert paper.status == "ok", paper.model_dump(mode="json")
        edition_id = paper.data["selected_edition_id"]
        report["paper"] = {
            "status": paper.status,
            "fabric_id": paper.data["paper"]["fabric_id"],
            "edition_id": edition_id,
        }

        found = await client.find_evidence(
            [{"ref": ref, "edition_id": edition_id}],
            "SQuAD v1.1 Test F1 93.2",
            max_chars=6000,
            retrieval_policy="v2",
        )
        assert found.status == "ok", found.model_dump(mode="json")
        hits = found.data["hits"]
        assert hits and any("93.2" in hit["evidence"]["excerpt"] for hit in hits)
        evidence_ids = [hit["evidence"]["evidence_id"] for hit in hits]
        report["evidence"] = {
            "status": found.status,
            "evidence_ids": evidence_ids,
            "returned_chars": found.data["returned_chars"],
            "pages": [hit["evidence"]["locator"]["page"] for hit in hits],
            "coverage": found.data["coverage"],
        }

        verified = await client.verify_claim(
            "BERT Large reports a SQuAD v1.1 test F1 score of 93.2.",
            [{"ref": ref, "edition_id": edition_id}],
            evidence_ids=evidence_ids,
        )
        assert verified.status == "partial", verified.model_dump(mode="json")
        receipt = verified.data["receipts"][0]
        assert receipt["grounding_status"] == "verified"
        assert receipt["assessment"]["verdict"] == "unavailable"
        replayed = await client.read_resource("citefabric://receipts/" + receipt["receipt_id"])
        assert replayed.data["receipt"] == receipt
        report["verification"] = {
            "status": verified.status,
            "receipt_id": receipt["receipt_id"],
            "grounding_status": receipt["grounding_status"],
            "claim_verdict": receipt["assessment"]["verdict"],
            "reason_code": receipt["assessment"]["reason_code"],
            "resource_replayed": True,
        }

        exported = await client.export_citations(
            [{"ref": ref, "edition_id": edition_id}],
            "bibtex",
            receipt_ids=[receipt["receipt_id"]],
        )
        assert exported.status == "ok", exported.model_dump(mode="json")
        manifest = exported.data["provenance_manifest"][0]
        assert manifest["receipt_ids"] == [receipt["receipt_id"]]
        assert manifest["grounding_status"] == "verified"
        report["citation"] = {
            "status": exported.status,
            "format": exported.data["format"],
            "content": exported.data["content"],
            "provenance_manifest": exported.data["provenance_manifest"],
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
