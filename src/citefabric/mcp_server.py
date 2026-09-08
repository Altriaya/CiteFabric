"""Exactly five tools, with explicit structured errors and bounded outputs."""

from __future__ import annotations

import asyncio

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server
from pydantic import BaseModel, ValidationError

from .client import CiteFabricClient
from .config import Config
from .models import (
    EvidenceRequest,
    ExportRequest,
    FabricError,
    GetRequest,
    Result,
    SearchRequest,
    VerifyRequest,
    new_id,
)
from .storage import dump

TOOLS: dict[str, tuple[type[BaseModel], str]] = {
    "search_papers": (
        SearchRequest,
        "Search academic sources; return deduplicated, version-aware papers and explicit provider failures.",
    ),
    "get_paper": (
        GetRequest,
        "Resolve a paper identifier and inspect editions, metadata provenance, conflicts and document candidates.",
    ),
    "find_evidence": (
        EvidenceRequest,
        "Find exact text passages in selected editions, with physical PDF pages and replayable hashes. Relevance is not claim support.",
    ),
    "verify_claim": (
        VerifyRequest,
        "Create a claim-to-evidence audit receipt. In 0.1 semantic verification is unavailable; never interprets lexical matches as support.",
    ),
    "export_citations": (
        ExportRequest,
        "Export locally resolved editions as BibTeX or CSL-JSON with a separate evidence provenance manifest.",
    ),
}
MAX_OUTPUT_BYTES = 128 * 1024


def bounded(result: Result, client: CiteFabricClient) -> dict:
    data = result.model_dump(mode="json")
    if len(dump(data).encode()) <= MAX_OUTPUT_BYTES:
        return data
    identifier = new_id()
    client.store.cache_put("result:" + identifier, data, 900)
    result = result.model_copy(deep=True)
    result.data = {
        "resource_uri": "citefabric://results/" + identifier,
        "message": "Result exceeds the inline budget. Read the result resource in bounded pages.",
        "items": [],
    }
    result.meta.truncated = True
    result.warnings = result.warnings[:10]
    result.errors = result.errors[:10]
    result.outcomes = result.outcomes[:20]
    result.meta.coverage = {}
    return result.model_dump(mode="json")


def create_server(client: CiteFabricClient) -> Server:
    server = Server(
        "citefabric",
        version="0.1.0",
        instructions="Paper existence, text grounding, and claim support are separate. 0.1 does not provide semantic support verdicts. Use explicit editions for evidence and citations.",
    )

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=name,
                description=description,
                inputSchema=model.model_json_schema(),
                outputSchema=Result.model_json_schema(),
                annotations=types.ToolAnnotations(
                    readOnlyHint=True, destructiveHint=False, openWorldHint=True
                ),
            )
            for name, (model, description) in TOOLS.items()
        ]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
        if name not in TOOLS:
            result = FabricError("unknown_tool", "Unknown CiteFabric tool.").result()
        else:
            try:
                request = TOOLS[name][0].model_validate(arguments)
                result = await getattr(client, name)(**request.model_dump(mode="json"))
            except ValidationError:
                result = FabricError(
                    "invalid_argument", "Arguments do not conform to the tool input schema."
                ).result()
        payload = bounded(result, client)
        # Validation happens before returning CallToolResult; the low-level SDK
        # intentionally bypasses its output validator for explicit result objects.
        Result.model_validate(payload)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=dump(payload))],
            structuredContent=payload,
            isError=result.status == "failed",
        )

    @server.list_resource_templates()
    async def resource_templates() -> list[types.ResourceTemplate]:
        return [
            types.ResourceTemplate(
                uriTemplate="citefabric://" + kind + "/{id}", name=kind, mimeType="application/json"
            )
            for kind in ("papers", "evidence", "receipts", "results")
        ]

    @server.read_resource()
    async def read_resource(uri):
        from urllib.parse import parse_qs, urlsplit

        parsed = urlsplit(str(uri))
        params = parse_qs(parsed.query)
        try:
            offset = int(params.get("offset", ["0"])[0])
            if offset < 0:
                raise ValueError
        except ValueError:
            result = FabricError(
                "invalid_argument", "Resource offset must be a nonnegative integer."
            ).result()
        else:
            result = await client.read_resource(str(uri).split("?", 1)[0])
        payload = dump(result.model_dump(mode="json"))
        if len(payload.encode()) > MAX_OUTPUT_BYTES:
            # Bounded text pages preserve the full JSON as an opaque serialized
            # document. Consumers concatenate chunks, then parse the JSON.
            chunk_size = 12000
            chunk = payload[offset : offset + chunk_size]
            next_offset = offset + len(chunk)
            next_uri = (
                str(uri).split("?", 1)[0] + "?offset=" + str(next_offset)
                if next_offset < len(payload)
                else None
            )
            payload = dump(
                dict(serialization="json_text_chunks", offset=offset, text=chunk, next_uri=next_uri)
            )
        return [ReadResourceContents(content=payload, mime_type="application/json")]

    return server


async def serve(config: Config | None = None):
    async with CiteFabricClient(config) as client:
        server = create_server(client)
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())


def main(config: Config | None = None):
    asyncio.run(serve(config))
