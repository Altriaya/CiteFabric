"""Exercise a saved real-paper run through a separate stdio MCP server."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(run_dir):
    manifest = json.loads((run_dir / "manifest.json").read_text())
    fixture = json.loads((run_dir / "cases.json").read_text())
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "citefabric", "--data-dir", manifest["data_dir"], "--offline"],
    )
    report = {"transport": "stdio", "resolutions": [], "queries": []}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed_tools = (await session.list_tools()).tools
            report["tools"] = [t.name for t in listed_tools]
            evidence_tool = next(t for t in listed_tools if t.name == "find_evidence")
            properties = evidence_tool.inputSchema["properties"]
            assert {"expand_query", "include_context", "retrieval_policy"} <= properties.keys()
            report["query_language"] = manifest.get("query_language", "en")
            selectors = [p["selector"] for p in manifest["papers"].values()]
            for selector in selectors:
                detail = await session.call_tool("get_paper", selector)
                assert not detail.isError and detail.structuredContent["status"] == "ok"
                report["resolutions"].append(detail.structuredContent)
            for case in fixture["cases"]:
                selector = manifest["papers"][case["paper"]]["selector"]
                found = await session.call_tool(
                    "find_evidence",
                    {
                        "papers": [selector],
                        "query": case["question_zh"]
                        if report["query_language"] == "zh"
                        else case["retrieval_query_en"],
                        **manifest["retrieval"],
                    },
                )
                baseline = json.loads((run_dir / f"{case['id']}.json").read_text())
                assert not found.isError
                assert found.structuredContent["status"] == baseline["retrieval"]["status"]
                hits = found.structuredContent["data"]["hits"]
                assert [h["evidence"]["evidence_id"] for h in hits] == [
                    h["evidence"]["evidence_id"] for h in baseline["retrieval"]["data"]["hits"]
                ]
                for hit in hits:
                    evidence_id = hit["evidence"]["evidence_id"]
                    resource = await session.read_resource("citefabric://evidence/" + evidence_id)
                    body = json.loads(resource.contents[0].text)
                    assert body["data"]["evidence"] == hit["evidence"]
                receipts = baseline["verification"]["data"]["receipts"]
                for receipt in receipts:
                    resource = await session.read_resource(
                        "citefabric://receipts/" + receipt["receipt_id"]
                    )
                    assert json.loads(resource.contents[0].text)["data"]["receipt"] == receipt
                report["queries"].append(
                    {
                        "case_id": case["id"],
                        "sdk_parity": True,
                        "evidence_resources_checked": len(hits),
                        "receipt_resources_checked": len(receipts),
                        "result": found.structuredContent,
                    }
                )
            exported = await session.call_tool(
                "export_citations", {"papers": selectors, "format": "bibtex"}
            )
            assert not exported.isError and exported.structuredContent["status"] == "ok"
            report["export"] = exported.structuredContent
    (run_dir / "mcp_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        f"MCP stdio: {len(selectors)} resolutions, {len(report['queries'])} queries, "
        "SDK parity, evidence/receipt resources and citation export passed."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    asyncio.run(run(parser.parse_args().run_dir))
