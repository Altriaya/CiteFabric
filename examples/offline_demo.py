"""Run with: uv run python examples/offline_demo.py [--data-dir PATH]."""

import argparse
import asyncio
import json
from pathlib import Path

from citefabric import CiteFabricClient, Config


async def main(data_dir: Path):
    source = Path(__file__).resolve().parents[1] / "docs/examples/source.txt"
    async with CiteFabricClient(Config(data_dir=data_dir, offline=True)) as client:
        imported = await client.import_document(source, title="Synthetic memory benchmark fixture")
        if imported.status == "failed":
            raise RuntimeError(imported.model_dump_json())
        selectors = [{"ref": imported.data["fabric_id"], "edition_id": imported.data["edition_id"]}]
        found = await client.find_evidence(selectors, "memory benchmark")
        ids = [hit["evidence"]["evidence_id"] for hit in found.data["hits"]]
        verification = await client.verify_claim(
            "Memory improves performance across benchmarks.", selectors, evidence_ids=ids
        )
        receipts = [receipt["receipt_id"] for receipt in verification.data["receipts"]]
        exported = await client.export_citations(selectors, "csl_json", receipt_ids=receipts)
        print(
            json.dumps(
                {
                    "example_only": True,
                    "paper": selectors[0],
                    "evidence": found.data["hits"],
                    "receipts": verification.data["receipts"],
                    "citations": exported.data,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".citefabric/demo"))
    asyncio.run(main(parser.parse_args().data_dir))
