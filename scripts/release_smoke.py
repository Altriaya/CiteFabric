"""Exercise the 0.1 golden path through a real stdio MCP server.

The selected edition must already have a parsed full-text document in the
workspace.  The server runs offline so this check isolates MCP transport,
identity resolution, evidence retrieval, receipt replay, and citation export.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def body(resource) -> dict:
    return json.loads(resource.contents[0].text)


async def run(args):
    selector = {"ref": args.paper, "edition_id": args.edition}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "citefabric", "--data-dir", str(args.data_dir.resolve()), "--offline"],
        env=dict(os.environ),
    )
    report = {
        "kind": "citefabric_0.1_stdio_release_smoke",
        "workspace": str(args.data_dir.resolve()),
        "selector": selector,
        "query": args.query,
        "claim": args.claim,
    }
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            report["tools"] = [tool.name for tool in tools]
            assert report["tools"] == [
                "search_papers",
                "get_paper",
                "find_evidence",
                "verify_claim",
                "export_citations",
            ]
            assert all(tool.outputSchema for tool in tools)

            paper = await session.call_tool("get_paper", selector)
            assert not paper.isError and paper.structuredContent["status"] == "ok"
            report["paper"] = {
                "status": paper.structuredContent["status"],
                "fabric_id": paper.structuredContent["data"]["paper"]["fabric_id"],
                "selected_edition_id": paper.structuredContent["data"]["selected_edition_id"],
            }

            found = await session.call_tool(
                "find_evidence",
                {
                    "papers": [selector],
                    "query": args.query,
                    "max_passages": 6,
                    "max_chars": 6000,
                    "retrieval_policy": "v2",
                },
            )
            assert not found.isError and found.structuredContent["status"] == "ok"
            hits = found.structuredContent["data"]["hits"]
            assert hits
            evidence_ids = [hit["evidence"]["evidence_id"] for hit in hits]
            evidence_replayed = []
            for hit in hits:
                expected = hit["evidence"]
                resource = await session.read_resource(
                    "citefabric://evidence/" + expected["evidence_id"]
                )
                restored = body(resource)["data"]["evidence"]
                assert restored == expected
                evidence_replayed.append(expected["evidence_id"])
            report["evidence"] = {
                "status": found.structuredContent["status"],
                "evidence_ids": evidence_ids,
                "returned_chars": found.structuredContent["data"]["returned_chars"],
                "resources_replayed": evidence_replayed,
            }

            verified = await session.call_tool(
                "verify_claim",
                {"claim": args.claim, "papers": [selector], "evidence_ids": evidence_ids},
            )
            assert not verified.isError and verified.structuredContent["status"] == "partial"
            receipts = verified.structuredContent["data"]["receipts"]
            assert len(receipts) == 1
            receipt = receipts[0]
            assert receipt["grounding_status"] == "verified"
            assert receipt["assessment"]["verdict"] == "unavailable"
            resource = await session.read_resource("citefabric://receipts/" + receipt["receipt_id"])
            assert body(resource)["data"]["receipt"] == receipt
            report["verification"] = {
                "status": verified.structuredContent["status"],
                "receipt_id": receipt["receipt_id"],
                "grounding_status": receipt["grounding_status"],
                "claim_verdict": receipt["assessment"]["verdict"],
                "reason_code": receipt["assessment"]["reason_code"],
                "resource_replayed": True,
            }

            exports = {}
            for format_ in ("bibtex", "csl_json"):
                exported = await session.call_tool(
                    "export_citations",
                    {
                        "papers": [selector],
                        "format": format_,
                        "receipt_ids": [receipt["receipt_id"]],
                    },
                )
                assert not exported.isError and exported.structuredContent["status"] == "ok"
                data = exported.structuredContent["data"]
                manifest = data["provenance_manifest"][0]
                assert manifest["receipt_ids"] == [receipt["receipt_id"]]
                assert manifest["grounding_status"] == "verified"
                exports[format_] = {
                    "status": exported.structuredContent["status"],
                    "content": data["content"],
                    "provenance_manifest": data["provenance_manifest"],
                }
            report["exports"] = exports

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("MCP release smoke passed: identity, evidence, receipt replay, BibTeX and CSL-JSON.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--paper", required=True)
    parser.add_argument("--edition", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--claim", required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
