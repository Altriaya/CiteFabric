import json
import os
import sys

import jsonschema
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typer.testing import CliRunner

from citefabric.cli import app
from citefabric.client import CiteFabricClient
from citefabric.mcp_server import MAX_OUTPUT_BYTES, TOOLS, bounded
from citefabric.models import Result


def test_cli_exit_codes_and_structured_json(tmp_path):
    runner = CliRunner()
    prefix = ["--data-dir", str(tmp_path / "data"), "--offline"]
    path = tmp_path / "text.txt"
    path.write_text("Memory improves task completion on Task A.")
    imported = runner.invoke(app, [*prefix, "import", str(path), "--json"])
    assert imported.exit_code == 0, imported.output
    ref = json.loads(imported.stdout)["data"]["fabric_id"]
    found = runner.invoke(app, [*prefix, "evidence", ref, "memory", "--json"])
    assert found.exit_code == 0
    verified = runner.invoke(app, [*prefix, "verify", "Memory helps", "--paper", ref, "--json"])
    assert verified.exit_code == 3
    assert (
        json.loads(verified.stdout)["data"]["receipts"][0]["assessment"]["verdict"] == "unavailable"
    )
    invalid = runner.invoke(app, [*prefix, "search", "memory", "--limit", "99", "--json"])
    assert invalid.exit_code == 2
    failed = runner.invoke(app, [*prefix, "search", "memory", "--sources", "crossref", "--json"])
    assert failed.exit_code == 4
    assert json.loads(failed.stdout)["outcomes"][0]["code"] == "offline"


async def test_stdio_protocol_and_resource_roundtrip(config, tmp_path):
    path = tmp_path / "text.txt"
    path.write_text("Memory improves task completion on Task A.")
    async with CiteFabricClient(config) as client:
        imported = await client.import_document(path)
        ref = imported.data["fabric_id"]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "citefabric", "--data-dir", str(config.data_dir), "--offline"],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            available = await session.list_tools()
            assert {tool.name for tool in available.tools} == set(TOOLS)
            for tool in available.tools:
                assert tool.outputSchema
            search = await session.call_tool(
                "find_evidence", {"papers": [{"ref": ref}], "query": "memory"}
            )
            assert not search.isError
            jsonschema.validate(search.structuredContent, Result.model_json_schema())
            assert json.loads(search.content[0].text) == search.structuredContent
            eid = search.structuredContent["data"]["hits"][0]["evidence"]["evidence_id"]
            resource = await session.read_resource("citefabric://evidence/" + eid)
            assert json.loads(resource.contents[0].text)["data"]["evidence"]["evidence_id"] == eid
            invalid = await session.call_tool("get_paper", {"unexpected": "value"})
            assert invalid.isError
            assert invalid.structuredContent["errors"][0]["code"] == "invalid_argument"


async def test_bounded_output_preserves_full_result_in_resource(config):
    async with CiteFabricClient(config) as client:
        original = Result(data={"items": ["long value " * 20000]})
        payload = bounded(original, client)
        assert len(json.dumps(payload).encode()) < MAX_OUTPUT_BYTES
        assert payload["meta"]["truncated"]
        restored = await client.read_resource(payload["data"]["resource_uri"])
        assert restored == original


def test_all_schemas_are_valid():
    jsonschema.Draft202012Validator.check_schema(Result.model_json_schema())
    for model, _ in TOOLS.values():
        schema = model.model_json_schema()
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
