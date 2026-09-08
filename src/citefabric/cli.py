"""CLI and stdio entrypoint. Machine mode emits one Result envelope on stdout."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from .client import CiteFabricClient
from .config import Config
from .models import FabricError, Result

app = typer.Typer(
    no_args_is_help=False,
    pretty_exceptions_enable=False,
    help="Search papers and preserve exact evidence. No semantic claim verifier in 0.1.",
)
Machine = Annotated[
    bool, typer.Option("--json", help="Emit the complete structured Result envelope.")
]


def emit(result: Result, machine: bool):
    if machine:
        typer.echo(result.model_dump_json())
    else:
        typer.echo(result.model_dump_json(indent=2))
    code = (
        2
        if any(e.code == "invalid_argument" for e in result.errors)
        else {"ok": 0, "no_results": 0, "partial": 3, "failed": 4}[result.status]
    )
    if code:
        raise typer.Exit(code)


def run(ctx: typer.Context, method: str, machine: bool, **kwargs):
    async def execute():
        async with CiteFabricClient(ctx.obj) as client:
            return await getattr(client, method)(**kwargs)

    try:
        result = asyncio.run(execute())
    except FabricError as exc:
        result = exc.result()
    emit(result, machine)


@app.callback(invoke_without_command=True)
def entry(
    ctx: typer.Context,
    data_dir: Annotated[
        Path | None, typer.Option("--data-dir", help="Use an isolated local workspace.")
    ] = None,
    offline: Annotated[
        bool | None,
        typer.Option("--offline/--online", help="Disable/enable provider network requests."),
    ] = None,
):
    try:
        ctx.obj = Config.load(data_dir=data_dir, offline=offline)
    except (ValidationError, OSError, ValueError):
        emit(FabricError("invalid_argument", "Invalid local configuration.").result(), True)
    if ctx.invoked_subcommand is None:
        from .mcp_server import main

        main(ctx.obj)


@app.command()
def serve(ctx: typer.Context):
    """Start the MCP server over stdio."""
    from .mcp_server import main

    main(ctx.obj)


@app.command()
def search(
    ctx: typer.Context,
    query: str,
    limit: int = 10,
    sources: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    open_access: Annotated[bool | None, typer.Option("--open-access/--any-access")] = None,
    sort: str = "relevance",
    evidence_ready: bool = False,
    cursor: str | None = None,
    json: Machine = False,
):
    """Search up to four providers with explicit degradation status."""
    run(
        ctx,
        "search_papers",
        json,
        query=query,
        limit=limit,
        sources=sources.split(",") if sources else None,
        filters=dict(year_from=year_from, year_to=year_to, open_access=open_access),
        sort=sort,
        evidence_ready=evidence_ready,
        cursor=cursor,
    )


@app.command()
def paper(
    ctx: typer.Context,
    ref: str,
    edition: str | None = None,
    refresh: bool = False,
    json: Machine = False,
):
    """Resolve a paper and inspect its editions."""
    run(ctx, "get_paper", json, ref=ref, edition_id=edition, refresh=refresh)


@app.command()
def evidence(
    ctx: typer.Context,
    ref: str,
    query: str,
    edition: str | None = None,
    max_passages: int = 6,
    max_chars: int = 6000,
    allow_abstract: bool = False,
    expand_query: bool = True,
    include_context: bool = True,
    retrieval_policy: str = "v2",
    json: Machine = False,
):
    """Find bounded exact text passages in one edition."""
    run(
        ctx,
        "find_evidence",
        json,
        papers=[dict(ref=ref, edition_id=edition)],
        query=query,
        max_passages=max_passages,
        max_chars=max_chars,
        allow_abstract=allow_abstract,
        expand_query=expand_query,
        include_context=include_context,
        retrieval_policy=retrieval_policy,
    )


@app.command()
def verify(
    ctx: typer.Context,
    claim: str,
    paper: Annotated[list[str], typer.Option("--paper")],
    edition: str | None = None,
    evidence_id: Annotated[list[str] | None, typer.Option("--evidence-id")] = None,
    context: str | None = None,
    json: Machine = False,
):
    """Create a traceable receipt; semantic verdict is unavailable in 0.1."""
    if edition and len(paper) != 1:
        emit(
            FabricError("invalid_argument", "--edition requires exactly one --paper.").result(),
            json,
        )
    run(
        ctx,
        "verify_claim",
        json,
        claim=claim,
        papers=[dict(ref=p, edition_id=edition) for p in paper],
        evidence_ids=evidence_id,
        context=context,
    )


@app.command()
def cite(
    ctx: typer.Context,
    refs: Annotated[list[str], typer.Argument()],
    format: str = "bibtex",
    edition: str | None = None,
    receipt: Annotated[list[str] | None, typer.Option("--receipt")] = None,
    json: Machine = False,
):
    """Export local metadata as BibTeX/CSL-JSON plus provenance."""
    if edition and len(refs) != 1:
        emit(
            FabricError("invalid_argument", "--edition requires exactly one reference.").result(),
            json,
        )
    run(
        ctx,
        "export_citations",
        json,
        papers=[dict(ref=p, edition_id=edition) for p in refs],
        format=format,
        receipt_ids=receipt,
    )


@app.command("import")
def import_file(
    ctx: typer.Context,
    path: Path,
    edition: str | None = None,
    title: str | None = None,
    json: Machine = False,
):
    """Import an explicitly selected PDF or UTF-8 text file."""
    run(ctx, "import_document", json, path=path, edition_id=edition, title=title)


@app.command()
def doctor(ctx: typer.Context, online: bool = False, json: Machine = False):
    """Check configuration and storage; --online also probes enabled providers."""
    run(ctx, "doctor", json, online=online)


if __name__ == "__main__":
    app()
