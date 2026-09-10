"""Round 4 evaluation tooling. Never import this module into product retrieval.

Commands: validate, prepare, seal, run, blind, score. Run consumes prepared queries only.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import platform
import random
import statistics
import subprocess
import sys
import time
import uuid
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pypdf import PdfReader

from citefabric import CiteFabricClient, Config
from citefabric.models import ExtractionSnapshot

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ("v2", "structured_v3")
LANGUAGES = ("en", "zh")
SCHEMA = ROOT / "benchmarks/round4/fixture.schema.json"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read(path: Path):
    return json.loads(path.read_bytes().decode("utf-8"))


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def write(path: Path, value):
    # No overwrites, including partial or previously failed experiments.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(items, key):
    result = {item[key]: item for item in items}
    require(len(result) == len(items), f"Duplicate {key}")
    return result


def schema_check(value, kind):
    require(value.get("kind") == kind, f"Expected {kind} file")
    schema = read(SCHEMA)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)


def check_review(review, frozen):
    if frozen:
        require(not review["saw_retrieval_outputs"], "Frozen annotation saw retrieval outputs")
        if review["independence"] == "independent_review":
            require(review["reviewer_ids"], "Independent review has no reviewer")
            require(review["author_id"] not in review["reviewer_ids"], "Author is own reviewer")


def validate_queries(queries, prior=()):
    schema_check(queries, "queries")
    papers = unique(queries["papers"], "paper_id")
    intents = unique(queries["intents"], "intent_id")
    for paper in papers.values():
        require(paper["filename"] not in {".pdf", "..pdf"}, "Invalid PDF filename")
    require(len({p["sha256"] for p in papers.values()}) == len(papers), "Duplicate source PDF")
    require(len({p["filename"] for p in papers.values()}) == len(papers), "Duplicate filename")
    for item in intents.values():
        require(item["paper_id"] in papers, "Unknown intent paper")
        check_review(item["equivalence_review"], queries["status"] == "frozen")
        visited = {item["intent_id"]}
        parent = item["parent_intent_id"]
        while parent is not None:
            require(parent in intents and parent not in visited, "Unknown or cyclic parent intent")
            require(intents[parent]["paper_id"] == item["paper_id"], "Parent crosses papers")
            visited.add(parent)
            parent = intents[parent]["parent_intent_id"]
    require({i["paper_id"] for i in intents.values()} == set(papers), "Paper has no intents")
    for previous in prior:
        validate_queries(previous)
        families = {p["family_id"] for p in previous["papers"]}
        hashes = {p["sha256"] for p in previous["papers"]}
        require(
            not families.intersection(p["family_id"] for p in papers.values()),
            "Paper family overlaps prior cohort",
        )
        require(
            not hashes.intersection(p["sha256"] for p in papers.values()),
            "Source overlaps prior cohort",
        )
    return papers, intents


def validate_sources(queries, input_dir):
    for paper in queries["papers"]:
        path = input_dir / paper["filename"]
        require(path.resolve().parent == input_dir.resolve(), "PDF escapes input directory")
        require(
            digest(path.read_bytes()) == paper["sha256"], f"PDF hash mismatch: {paper['paper_id']}"
        )
        require(
            len(PdfReader(path).pages) == paper["pages"],
            f"PDF page count mismatch: {paper['paper_id']}",
        )


def validate_gold(queries_path, gold, snapshots=None):
    queries = read(queries_path)
    papers, intents = validate_queries(queries)
    schema_check(gold, "gold")
    require(gold["queries_sha256"] == digest(queries_path.read_bytes()), "Gold query hash mismatch")
    for field in ("protocol_version", "cohort_id"):
        require(gold[field] == queries[field], f"Gold {field} mismatch")
    cases = unique(gold["cases"], "intent_id")
    require(set(cases) == set(intents), "Gold must cover every intent exactly once")
    for key, case in cases.items():
        require(case["paper_id"] == intents[key]["paper_id"], "Gold paper mismatch")
        paper = papers[case["paper_id"]]
        require(case["source_sha256"] == paper["sha256"], "Gold source mismatch")
        check_review(case["review"], queries["status"] == "frozen")
        spans = unique(case["spans"], "span_id")
        requirements = unique(case["requirements"], "requirement_id")
        for span in spans.values():
            require(span["end"] > span["start"], "Invalid span bounds")
            require(span["page"] <= paper["pages"], "Span outside PDF pages")
            require(len(span["quote"]) == span["end"] - span["start"], "Quote length mismatch")
        for requirement in requirements.values():
            require(set(requirement["span_ids"]) <= spans.keys(), "Unknown requirement span")
            require(
                all(v["page"] <= paper["pages"] for v in requirement["visual_requirements"]),
                "Visual requirement outside pages",
            )
        for sufficient in case["sufficient_sets"]:
            require(set(sufficient) <= requirements.keys(), "Unknown sufficient-set requirement")
        if case["extraction_text_sha256"] is None:
            require(
                not spans and "extraction_gap" in case["tags"],
                "Missing extraction hash requires visual-only extraction_gap gold",
            )
        if snapshots is not None:
            raw = snapshots.get(case["paper_id"])
            if raw is None:
                require(
                    case["extraction_text_sha256"] is None and not spans,
                    "Gold cannot replay: missing extraction snapshot",
                )
                continue
            snapshot = ExtractionSnapshot.model_validate(raw)
            require(
                snapshot.text_hash == "sha256:" + case["extraction_text_sha256"],
                "Gold extraction hash mismatch",
            )
            for span in spans.values():
                require(span["unit_index"] < len(snapshot.text_units), "Unknown extraction unit")
                unit = snapshot.text_units[span["unit_index"]]
                require(unit.page == span["page"], "Span page/unit mismatch")
                require(
                    unit.text[span["start"] : span["end"]] == span["quote"],
                    "Gold span does not replay",
                )
    return cases


def provenance():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()

    files = sorted((ROOT / "src/citefabric").glob("*.py")) + [
        Path(__file__),
        SCHEMA,
        ROOT / "uv.lock",
        ROOT / "pyproject.toml",
        ROOT / "scripts/round4_synthetic.py",
    ]
    files += sorted((ROOT / "benchmarks/round4").glob("*.md"))
    return {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "diff_sha256": digest(subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)),
        "files": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in files},
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {p: version(p) for p in ("citefabric", "mcp", "pypdf", "jsonschema")},
    }


async def prepare(queries_path, input_dir, output_dir):
    queries = read(queries_path)
    validate_queries(queries)
    validate_sources(queries, input_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "queries.json").write_bytes(queries_path.read_bytes())
    manifest = {
        "kind": "round4_prepared",
        "created_at": datetime.now(UTC).isoformat(),
        "queries_sha256": digest((output_dir / "queries.json").read_bytes()),
        "original_queries_sha256": digest(queries_path.read_bytes()),
        "provenance": provenance(),
        "policies": {},
        "snapshots": {},
        "config": Config(offline=True, parse_timeout=60).model_dump(
            mode="json",
            exclude={"data_dir", "openalex_api_key", "semantic_scholar_api_key", "contact_email"},
        ),
        "complete": False,
    }
    for policy in POLICIES:
        directory = output_dir / "workspaces" / policy
        results = {}
        async with CiteFabricClient(Config(data_dir=directory, **manifest["config"])) as client:
            for paper in queries["papers"]:
                started = time.perf_counter()
                try:
                    imported = await client.import_document(
                        input_dir / paper["filename"], title=paper["title"]
                    )
                    data = imported.data or {}
                    snapshot = (
                        client.store.extraction(data["extraction_id"]).model_dump(mode="json")
                        if data.get("extraction_id")
                        else None
                    )
                    results[paper["paper_id"]] = {
                        "import": imported.model_dump(mode="json"),
                        "snapshot": snapshot,
                        "selector": {"ref": data["fabric_id"], "edition_id": data["edition_id"]}
                        if snapshot
                        else None,
                    }
                    if policy == "v2":
                        manifest["snapshots"][paper["paper_id"]] = snapshot
                    elif snapshot and manifest["snapshots"].get(paper["paper_id"]):
                        require(
                            snapshot["text_hash"]
                            == manifest["snapshots"][paper["paper_id"]]["text_hash"],
                            "Policies have different extractions",
                        )
                except Exception as exc:
                    results[paper["paper_id"]] = {
                        "selector": None,
                        "snapshot": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                results[paper["paper_id"]]["import_seconds"] = time.perf_counter() - started
        manifest["policies"][policy] = results
    manifest["complete"] = True
    write(output_dir / "prepared.json", manifest)
    write(output_dir / "extractions.json", manifest["snapshots"])
    return manifest


class ResponseRecorder:
    """Capture canonical full JSON-RPC response bytes, including duplicated MCP content.

    This measures reserialized messages, not raw pipe whitespace or network framing.
    Requests are sequential, so each request owns the responses recorded until completion.
    """

    def __init__(self, stream):
        self.stream = stream
        self.messages = []

    async def __aenter__(self):
        await self.stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.stream.__aexit__(*args)

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.stream.__anext__()
        if not isinstance(message, Exception):
            value = message.message.model_dump(mode="json", by_alias=True, exclude_none=True)
            if "id" in value and ("result" in value or "error" in value):
                self.messages.append(value)
        return message


async def read_evidence(session, evidence_id):
    uri = "citefabric://evidence/" + evidence_id
    pieces = []
    seen = set()
    while uri:
        require(uri not in seen and len(seen) < 100, "Invalid resource pagination")
        seen.add(uri)
        response = await session.read_resource(uri)
        value = json.loads("".join(c.text for c in response.contents))
        if value.get("serialization") != "json_text_chunks":
            require(not pieces, "Resource pagination changed format")
            return value
        require(value["offset"] == sum(map(len, pieces)), "Resource chunk gap")
        pieces.append(value["text"])
        uri = value["next_uri"]
    return json.loads("".join(pieces))


def seal(
    prepared_dir, gold_path, output_path, custodian, prior_paths=(), max_chars=6000, repeats=3
):
    require(custodian.strip(), "Custodian required")
    require(max_chars in {6000, 12000} and repeats >= 3, "Invalid sealed budget or repetitions")
    queries_path = prepared_dir / "queries.json"
    queries = read(queries_path)
    validate_queries(queries, [read(p) for p in prior_paths])
    require(
        queries["status"] == "frozen",
        "Set query status to frozen before preparation and gold annotation",
    )
    require(not (prepared_dir / "run-started.json").exists(), "Cannot seal an opened run")
    prepared = read(prepared_dir / "prepared.json")
    require(
        prepared["queries_sha256"] == digest(queries_path.read_bytes()), "Prepared queries changed"
    )
    validate_gold(queries_path, read(gold_path), prepared["snapshots"])
    current = provenance()
    require(
        current["files"] == prepared["provenance"]["files"],
        "Code or protocol changed since preparation",
    )
    record = {
        "kind": "round4_seal",
        "sealed_at": datetime.now(UTC).isoformat(),
        "custodian": custodian,
        "queries_sha256": digest(queries_path.read_bytes()),
        "gold_sha256": digest(gold_path.read_bytes()),
        "prepared_sha256": digest((prepared_dir / "prepared.json").read_bytes()),
        "prior_queries_sha256": [digest(p.read_bytes()) for p in prior_paths],
        "provenance": current,
        "independence_verified": False,
        "run_parameters": {"max_chars": max_chars, "repeats": repeats, "seed": 20260909},
        "notice": "Hash commitment only; independent custody and reviewer identities require external evidence.",
    }
    write(output_path, record)
    return record


async def run(prepared_dir, output_dir, repeats=3, max_chars=6000, seed=20260909, seal_path=None):
    require(repeats >= 3, "At least three warm repetitions required")
    require(max_chars in {6000, 12000}, "Unsupported evaluation budget")
    queries = read(prepared_dir / "queries.json")
    validate_queries(queries)
    manifest = read(prepared_dir / "prepared.json")
    require(manifest["complete"], "Incomplete preparation")
    require(
        manifest["queries_sha256"] == digest((prepared_dir / "queries.json").read_bytes()),
        "Prepared queries changed",
    )
    current = provenance()
    require(
        current["files"] == manifest["provenance"]["files"],
        "Code or protocol changed since preparation",
    )
    commitment = read(seal_path) if seal_path else None
    for field in ("python", "packages", "platform"):
        require(
            current[field] == manifest["provenance"][field],
            "Execution environment changed since preparation",
        )
    if commitment:
        require(commitment["kind"] == "round4_seal", "Invalid seal kind")
        require(commitment["queries_sha256"] == manifest["queries_sha256"], "Seal query mismatch")
        require(
            commitment["prepared_sha256"] == digest((prepared_dir / "prepared.json").read_bytes()),
            "Seal preparation mismatch",
        )
        require(commitment["provenance"]["files"] == current["files"], "Seal code mismatch")
        require(
            commitment["run_parameters"]
            == {"max_chars": max_chars, "repeats": repeats, "seed": seed},
            "Run parameters differ from seal",
        )
    require(queries["split"] != "holdout" or commitment is not None, "Holdout run requires a seal")
    require(
        not (prepared_dir / "run-started.json").exists(),
        "Prepared workspaces already used; prepare fresh workspaces for a new run",
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    write(
        prepared_dir / "run-started.json",
        {"output": str(output_dir.resolve()), "started_at": datetime.now(UTC).isoformat()},
    )
    queries_file = output_dir / "queries.json"
    # Keep gold binding to the exact prepared queries bytes.
    queries_file.write_bytes((prepared_dir / "queries.json").read_bytes())
    rows = []
    rng = random.Random(seed)
    report = {
        "kind": "round4_run",
        "run_id": str(uuid.uuid4()),
        "complete": False,
        "created_at": datetime.now(UTC).isoformat(),
        "provenance": current,
        "queries_sha256": digest(queries_file.read_bytes()),
        "prepared_sha256": digest((prepared_dir / "prepared.json").read_bytes()),
        "seed": seed,
        "repeats": repeats,
        "max_chars": max_chars,
        "max_passages": 6,
        "allow_abstract": False,
        "expand_query": True,
        "include_context": True,
        "cost_unit": "canonical_utf8_jsonrpc_response_bytes",
        "tokens": None,
        "gold_access": "No gold argument or gold file opened; process API isolation, not OS sandboxing",
        "preparation": manifest,
        "seal": commitment,
        "rows": rows,
    }
    async with AsyncExitStack() as stack:
        sessions = {}
        for policy in POLICIES:
            config_env = {
                "CITEFABRIC_" + k.upper(): ",".join(v) if isinstance(v, list) else str(v)
                for k, v in manifest["config"].items()
            }
            config_env["CITEFABRIC_CONFIG"] = str((output_dir / "absent-config.toml").resolve())
            params = StdioServerParameters(
                command=sys.executable,
                args=[
                    "-m",
                    "citefabric",
                    "--offline",
                    "--data-dir",
                    str((prepared_dir / "workspaces" / policy).resolve()),
                ],
                env=config_env,
            )
            reader, writer = await stack.enter_async_context(stdio_client(params))
            recorder = ResponseRecorder(reader)
            session = await stack.enter_async_context(ClientSession(recorder, writer))
            await session.initialize()
            sessions[policy] = session, recorder
        # A distinct first pass captures cold/lazy-index behavior; it is not scored as warm latency.
        for repetition in range(repeats + 1):
            jobs = [(i, lang) for i in queries["intents"] for lang in LANGUAGES]
            rng.shuffle(jobs)
            for intent, lang in jobs:
                order = list(POLICIES)
                rng.shuffle(order)
                for policy in order:
                    session, recorder = sessions[policy]
                    recorder.messages.clear()
                    row = {
                        "intent_id": intent["intent_id"],
                        "paper_id": intent["paper_id"],
                        "language": lang,
                        "policy": policy,
                        "repetition": repetition,
                        "phase": "first_pass" if repetition == 0 else "warm",
                        "replay_integrity": False,
                    }
                    imported = manifest["policies"][policy][intent["paper_id"]]
                    started = time.perf_counter()
                    if not imported["selector"]:
                        row.update(
                            status="import_failed",
                            error=imported.get("error", "No extraction"),
                            evidence=[],
                            query_seconds=None,
                            response_bytes=0,
                            audit_bytes=0,
                        )
                    else:
                        try:
                            async with asyncio.timeout(130):
                                found = await session.call_tool(
                                    "find_evidence",
                                    {
                                        "papers": [imported["selector"]],
                                        "query": intent["query"][lang],
                                        "retrieval_policy": policy,
                                        "max_chars": max_chars,
                                        "max_passages": 6,
                                        "allow_abstract": False,
                                        "expand_query": True,
                                        "include_context": True,
                                    },
                                )
                            row["query_seconds"] = time.perf_counter() - started
                            row["response_bytes"] = sum(len(encoded(m)) for m in recorder.messages)
                            row["response_messages"] = list(recorder.messages)
                            payload = found.structuredContent
                            require(payload is not None, "Missing structured MCP result")
                            row["retrieval"] = payload
                            row["status"] = payload["status"]
                            row["evidence"] = [
                                h["evidence"] for h in (payload.get("data") or {}).get("hits", [])
                            ]
                            row["budget_ok"] = (
                                len(row["evidence"]) <= 6
                                and sum(len(e["excerpt"]) for e in row["evidence"]) <= max_chars
                            )
                            for evidence in row["evidence"]:
                                async with asyncio.timeout(130):
                                    checked = await read_evidence(session, evidence["evidence_id"])
                                require(
                                    (checked.get("data") or {}).get("evidence") == evidence,
                                    "MCP evidence replay mismatch",
                                )
                                require(
                                    evidence["source_hash"]
                                    == "sha256:"
                                    + next(
                                        p["sha256"]
                                        for p in queries["papers"]
                                        if p["paper_id"] == intent["paper_id"]
                                    ),
                                    "Evidence crosses documents",
                                )
                                require(
                                    evidence["edition_id"] == imported["selector"]["edition_id"],
                                    "Evidence crosses editions",
                                )
                            row["audit_messages"] = list(recorder.messages)
                            row["replay_integrity"] = True
                            row["audit_bytes"] = sum(len(encoded(m)) for m in recorder.messages)
                        except Exception as exc:
                            row.update(
                                status="execution_failed", error=f"{type(exc).__name__}: {exc}"
                            )
                            row.setdefault("evidence", [])
                            row.setdefault("query_seconds", time.perf_counter() - started)
                            row.setdefault(
                                "response_bytes", sum(len(encoded(m)) for m in recorder.messages)
                            )
                            row["audit_bytes"] = sum(len(encoded(m)) for m in recorder.messages)
                    rows.append(row)
                    # Append-only journal retains completed requests even if the process is interrupted.
                    with (output_dir / "journal.jsonl").open(
                        "a", encoding="utf-8", newline="\n"
                    ) as stream:
                        stream.write(encoded(row).decode() + "\n")
    report["completed_at"] = datetime.now(UTC).isoformat()
    report["end_provenance"] = provenance()
    report["complete"] = report["end_provenance"]["files"] == current["files"]
    write(output_dir / "run.json", report)
    require(report["complete"], "Code changed during run; incomplete record retained")
    return report


def selected_rows(run_data, queries):
    require(run_data["complete"], "Run incomplete")
    require(run_data["repeats"] >= 3, "Run has fewer than three repetitions")
    expected = {
        (i["intent_id"], lang, policy, rep)
        for i in queries["intents"]
        for lang in LANGUAGES
        for policy in POLICIES
        for rep in range(run_data["repeats"] + 1)
    }
    keyed = {
        (r["intent_id"], r["language"], r["policy"], r["repetition"]): r for r in run_data["rows"]
    }
    require(
        len(keyed) == len(run_data["rows"]) and set(keyed) == expected,
        "Run matrix missing or duplicated rows",
    )
    # First warm response is preselected; never pick the best of repeated responses.
    return [r for r in run_data["rows"] if r["repetition"] == 1]


def blind(run_dir, output_dir, key_path):
    require(not key_path.exists(), "Blinding key already exists")
    require(
        not key_path.resolve().is_relative_to(output_dir.resolve()),
        "Private key must be outside reviewer directory",
    )
    data = read(run_dir / "run.json")
    queries = read(run_dir / "queries.json")
    require(
        data["queries_sha256"] == digest((run_dir / "queries.json").read_bytes()),
        "Run query hash mismatch",
    )
    papers, intents = validate_queries(queries)
    rows = selected_rows(data, queries)
    # A private, randomly generated seed must not be included in the reviewer package.
    seed = random.SystemRandom().getrandbits(128)
    rng = random.Random(seed)
    rng.shuffle(rows)
    items, mapping = [], {}
    for row in rows:
        item_id = uuid.UUID(int=rng.getrandbits(128)).hex
        intent = intents[row["intent_id"]]
        evidence_list, evidence_map = [], {}
        for n, evidence in enumerate(row["evidence"], 1):
            alias = f"E{n}"
            loc = evidence["locator"]
            evidence_list.append(
                {
                    "alias": alias,
                    "excerpt": evidence["excerpt"],
                    "page": loc["page"],
                    "start": loc["char_start"],
                    "end": loc["char_end"],
                }
            )
            evidence_map[alias] = evidence["evidence_id"]
        items.append(
            {
                "item_id": item_id,
                "intent_id": row["intent_id"],
                "language": row["language"],
                "paper_id": row["paper_id"],
                "title": papers[row["paper_id"]]["title"],
                "edition": papers[row["paper_id"]]["edition_label"],
                "query": intent["query"][row["language"]],
                "claim": intent["claim"][row["language"]],
                "evidence": evidence_list,
            }
        )
        mapping[item_id] = {
            "intent_id": row["intent_id"],
            "language": row["language"],
            "policy": row["policy"],
            "evidence_ids": evidence_map,
        }
    package = {"kind": "round4_blind", "run_id": data["run_id"], "items": items}
    output_dir.mkdir(parents=True, exist_ok=False)
    write(output_dir / "items.json", package)
    template = {
        "reviewer_id": "REPLACE_WITH_REVIEWER_ID",
        "package_sha256": digest((output_dir / "items.json").read_bytes()),
        "ratings": [
            {
                "item_id": i["item_id"],
                "sufficiency": None,
                "requirements": {},
                "harmful_mismatch": None,
                "mismatch_types": [],
                "limitation_preserved": None,
                "failure_stage": None,
                "evidence_aliases": [],
                "rationale": "",
            }
            for i in items
        ],
    }
    write(output_dir / "rating-template.json", template)
    write(
        key_path,
        {
            "run_sha256": digest((run_dir / "run.json").read_bytes()),
            "package_sha256": template["package_sha256"],
            "seed": seed,
            "mapping": mapping,
        },
    )
    return package


def validate_ratings(review, package, gold_cases):
    require(
        isinstance(review.get("reviewer_id"), str)
        and review["reviewer_id"] not in {"", "REPLACE_WITH_REVIEWER_ID"},
        "Missing reviewer identity",
    )
    items = unique(package["items"], "item_id")
    ratings = unique(review["ratings"], "item_id")
    require(set(ratings) == set(items), "Every blind item must be scored exactly once")
    for item_id, rating in ratings.items():
        case = gold_cases[items[item_id]["intent_id"]]
        applicable = case["reference_verdict"] != "insufficient"
        allowed = {"complete", "partial", "none"} if applicable else {"not_applicable"}
        require(rating["sufficiency"] in allowed, "Invalid sufficiency for gold verdict")
        requirements = {r["requirement_id"] for r in case["requirements"]}
        require(
            set(rating["requirements"]) == requirements, "Incomplete requirement coverage ratings"
        )
        require(
            set(rating["requirements"].values()) <= {"present", "missing", "ambiguous"},
            "Invalid coverage state",
        )
        if rating["sufficiency"] == "complete":
            require(
                any(
                    all(rating["requirements"][r] == "present" for r in s)
                    for s in case["sufficient_sets"]
                ),
                "Complete lacks sufficient requirements",
            )
        require(type(rating["harmful_mismatch"]) is bool, "Missing mismatch judgment")
        require(
            set(rating["mismatch_types"])
            <= {"wrong_dataset", "wrong_model", "wrong_metric", "wrong_scope", "wrong_version"},
            "Invalid mismatch type",
        )
        require(
            bool(rating["mismatch_types"]) == rating["harmful_mismatch"],
            "Mismatch types inconsistent",
        )
        required_limit = applicable and "scope_limitation" in case["tags"]
        require(
            type(rating["limitation_preserved"]) is bool
            if required_limit
            else rating["limitation_preserved"] is None,
            "Invalid limitation rating",
        )
        require(
            rating["failure_stage"]
            in {
                "import",
                "extraction",
                "candidate_recall",
                "selection",
                "budget",
                "relation_ambiguity",
                "language",
                "annotation",
                "none",
            },
            "Invalid failure stage",
        )
        aliases = {e["alias"] for e in items[item_id]["evidence"]}
        require(set(rating["evidence_aliases"]) <= aliases, "Unknown cited evidence alias")
        require(rating["rationale"].strip(), "Missing review rationale")
        if (
            rating["sufficiency"] in {"complete", "partial"}
            or rating["harmful_mismatch"]
            or rating["limitation_preserved"]
        ):
            require(rating["evidence_aliases"], "Evidence judgment has no cited evidence")
    return ratings


def metric(rows, predicate, value):
    groups = {}
    numerator = denominator = 0
    for row in rows:
        if predicate(row):
            score_value = int(value(row))
            groups.setdefault(row["family_id"], []).append(score_value)
            numerator += score_value
            denominator += 1
    return {
        "numerator": numerator,
        "denominator": denominator,
        "paper_macro": statistics.mean(statistics.mean(v) for v in groups.values())
        if groups
        else None,
        "per_family": {
            k: {"numerator": sum(v), "denominator": len(v), "rate": statistics.mean(v)}
            for k, v in groups.items()
        },
    }


def paired_interval(left, right, seed=20260909):
    require(set(left) == set(right), "Paired metric has unmatched families")
    if len(left) < 2:
        return None
    deltas = [right[k]["rate"] - left[k]["rate"] for k in sorted(left)]
    rng = random.Random(seed)
    samples = sorted(statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(10000))
    return {
        "delta": statistics.mean(deltas),
        "ci95": [samples[249], samples[9749]],
        "clusters": len(deltas),
        "resamples": 10000,
        "seed": seed,
    }


def score(
    run_dir, package_path, key_path, gold_path, review_paths, output_path, adjudication_path=None
):
    data = read(run_dir / "run.json")
    queries_path = run_dir / "queries.json"
    queries = read(queries_path)
    gold = read(gold_path)
    cases = validate_gold(queries_path, gold, data["preparation"]["snapshots"])
    require(data["queries_sha256"] == digest(queries_path.read_bytes()), "Run queries changed")
    if data.get("seal"):
        require(
            data["seal"]["gold_sha256"] == digest(gold_path.read_bytes()),
            "Gold changed after sealing",
        )
    papers, intents = validate_queries(queries)
    package, key = read(package_path), read(key_path)
    require(package["run_id"] == data["run_id"], "Blind package belongs to another run")
    require(key["package_sha256"] == digest(package_path.read_bytes()), "Blind package changed")
    require(
        key["run_sha256"] == digest((run_dir / "run.json").read_bytes()),
        "Run changed after blinding",
    )
    require(len(review_paths) == 2, "Exactly two independent rating files required")
    reviews = [read(p) for p in review_paths]
    require(reviews[0]["reviewer_id"] != reviews[1]["reviewer_id"], "Reviewers must differ")
    for review in reviews:
        require(review["package_sha256"] == key["package_sha256"], "Review package hash mismatch")
    ratings = [validate_ratings(r, package, cases) for r in reviews]
    fields = (
        "sufficiency",
        "requirements",
        "harmful_mismatch",
        "mismatch_types",
        "limitation_preserved",
        "failure_stage",
    )
    conflicts = [i for i in ratings[0] if any(ratings[0][i][f] != ratings[1][i][f] for f in fields)]
    adjudicated = None
    if adjudication_path:
        review = read(adjudication_path)
        require(
            review["reviewer_id"] not in {r["reviewer_id"] for r in reviews},
            "Adjudicator must differ",
        )
        require(review["package_sha256"] == key["package_sha256"], "Adjudication hash mismatch")
        adjudicated = validate_ratings(review, package, cases)
    require(
        not conflicts or adjudicated is not None,
        "Unresolved reviewer disagreement; provide complete adjudication file",
    )
    selected = {
        (r["intent_id"], r["language"], r["policy"]): r for r in selected_rows(data, queries)
    }
    require(set(key["mapping"]) == set(ratings[0]), "Incomplete private blinding mapping")
    require(
        {(m["intent_id"], m["language"], m["policy"]) for m in key["mapping"].values()}
        == set(selected),
        "Invalid paired blinding mapping",
    )
    rows = []
    blind_items = unique(package["items"], "item_id")
    for item_id, mapping in key["mapping"].items():
        rating = adjudicated[item_id] if item_id in conflicts else ratings[0][item_id]
        intent = intents[mapping["intent_id"]]
        case = cases[mapping["intent_id"]]
        result = selected[(mapping["intent_id"], mapping["language"], mapping["policy"])]
        item = blind_items[item_id]
        require(
            item["intent_id"] == mapping["intent_id"] and item["language"] == mapping["language"],
            "Blind key disagrees with item",
        )
        require(item["paper_id"] == intent["paper_id"], "Blind item paper mismatch")
        require(item["query"] == intent["query"][mapping["language"]], "Blind query mismatch")
        require(
            mapping["evidence_ids"]
            == {f"E{n}": e["evidence_id"] for n, e in enumerate(result["evidence"], 1)},
            "Blind evidence mapping changed",
        )
        require(
            item["evidence"]
            == [
                {
                    "alias": f"E{n}",
                    "excerpt": e["excerpt"],
                    "page": e["locator"]["page"],
                    "start": e["locator"]["char_start"],
                    "end": e["locator"]["char_end"],
                }
                for n, e in enumerate(result["evidence"], 1)
            ],
            "Blind excerpts changed",
        )
        usable = (
            result["status"] in {"ok", "partial", "no_results"}
            and result["replay_integrity"]
            and result.get("budget_ok", False)
        )
        rows.append(
            {
                **mapping,
                "item_id": item_id,
                "family_id": papers[intent["paper_id"]]["family_id"],
                "paper_id": intent["paper_id"],
                "domain": papers[intent["paper_id"]]["domain"],
                "independent_intent": intent["parent_intent_id"] is None,
                "verdict": case["reference_verdict"],
                "tags": case["tags"],
                "rating": rating,
                "usable": usable,
                "esr": usable
                and rating["sufficiency"] == "complete"
                and not rating["harmful_mismatch"],
            }
        )
    metrics, comparisons = {}, {}
    for lang in LANGUAGES:
        metrics[lang] = {}
        for policy in POLICIES:
            subset = [
                r
                for r in rows
                if r["independent_intent"] and r["language"] == lang and r["policy"] == policy
            ]
            metrics[lang][policy] = {
                "esr": metric(subset, lambda r: r["verdict"] != "insufficient", lambda r: r["esr"]),
                "supported_esr": metric(
                    subset, lambda r: r["verdict"] == "supported", lambda r: r["esr"]
                ),
                "contradicted_esr": metric(
                    subset, lambda r: r["verdict"] == "contradicted", lambda r: r["esr"]
                ),
                "limitation": metric(
                    subset,
                    lambda r: r["verdict"] != "insufficient" and "scope_limitation" in r["tags"],
                    lambda r: r["usable"] and r["rating"]["limitation_preserved"],
                ),
                "harmful_mismatch": metric(
                    subset,
                    lambda r: "condition_counterexample" in r["tags"],
                    lambda r: r["rating"]["harmful_mismatch"],
                ),
                "insufficient_mismatch": metric(
                    subset,
                    lambda r: r["verdict"] == "insufficient",
                    lambda r: r["rating"]["harmful_mismatch"],
                ),
            }
        comparisons[lang] = paired_interval(
            metrics[lang]["v2"]["esr"]["per_family"],
            metrics[lang]["structured_v3"]["esr"]["per_family"],
        )
        for policy in POLICIES:
            subset = [
                r
                for r in rows
                if r["independent_intent"] and r["language"] == lang and r["policy"] == policy
            ]
            metrics[lang][policy]["answerable_counterexample_mismatch"] = metric(
                subset,
                lambda r: (
                    r["verdict"] != "insufficient" and "condition_counterexample" in r["tags"]
                ),
                lambda r: r["rating"]["harmful_mismatch"],
            )
            strata = {}
            for field in ("domain", "tags"):
                values = sorted(
                    {v for r in subset for v in (r[field] if field == "tags" else [r[field]])}
                )
                strata[field] = {
                    value: metric(
                        subset,
                        lambda r, value=value, field=field: (
                            r["verdict"] != "insufficient"
                            and (value in r[field] if field == "tags" else r[field] == value)
                        ),
                        lambda r: r["esr"],
                    )
                    for value in values
                }
            metrics[lang][policy]["strata_esr"] = strata
    costs = {}
    for policy in POLICIES:
        costs[policy] = {}
        for lang in LANGUAGES:
            warm = [
                r
                for r in data["rows"]
                if r["phase"] == "warm"
                and r["policy"] == policy
                and r["language"] == lang
                and intents[r["intent_id"]]["parent_intent_id"] is None
            ]
            timing = {}
            for r in warm:
                if r["query_seconds"] is not None:
                    timing.setdefault(r["intent_id"], []).append(r["query_seconds"])
            medians = sorted(statistics.median(v) for v in timing.values())
            costs[policy][lang] = {
                "mean_response_bytes": statistics.mean(r["response_bytes"] for r in warm),
                "mean_audit_bytes": statistics.mean(r["audit_bytes"] for r in warm),
                "warm_p95_seconds": medians[max(0, math.ceil(len(medians) * 0.95) - 1)]
                if medians
                else None,
                "timed_intents": len(medians),
                "requests": len(warm),
            }
    report = {
        "kind": "round4_scores",
        "run_id": data["run_id"],
        "metrics": metrics,
        "paired_esr": comparisons,
        "costs": costs,
        "cost_unit": data["cost_unit"],
        "integrity": {
            "requests": len(data["rows"]),
            "requests_with_failed_replay_or_import": sum(
                not r["replay_integrity"] for r in data["rows"]
            ),
            "requests_with_budget_violation": sum(
                r.get("budget_ok") is False for r in data["rows"]
            ),
            "gold_cases_without_text_snapshot": sum(
                c["extraction_text_sha256"] is None for c in gold["cases"]
            ),
        },
        "cohort": {
            "split": queries["split"],
            "status": queries["status"],
            "sealed": data.get("seal") is not None,
            "families": len({p["family_id"] for p in papers.values()}),
            "independent_intents": sum(i["parent_intent_id"] is None for i in intents.values()),
            "variants": sum(i["parent_intent_id"] is not None for i in intents.values()),
            "gold_review_modes": sorted({c["review"]["independence"] for c in cases.values()}),
        },
        "review_disagreements": conflicts,
        "agreement_before_adjudication": {
            f: sum(ratings[0][i][f] == ratings[1][i][f] for i in ratings[0]) / len(ratings[0])
            for f in ("sufficiency", "harmful_mismatch")
        },
        "rows": rows,
        "input_hashes": {
            "gold": digest(gold_path.read_bytes()),
            "package": digest(package_path.read_bytes()),
            "key": digest(key_path.read_bytes()),
            "reviews": [digest(p.read_bytes()) for p in review_paths],
            "adjudication": digest(adjudication_path.read_bytes()) if adjudication_path else None,
        },
        "promotion": {
            "status": "not_evaluated",
            "reason": "Metrics are not promotion approval. Independent custody, prior cohorts, freeze record, all G0/G1/G2/G3 checks and human decision are required.",
        },
        "failure_counts": {
            p: sum(
                r["status"] in {"execution_failed", "import_failed", "failed"}
                for r in data["rows"]
                if r["policy"] == p
            )
            for p in POLICIES
        },
    }
    write(output_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validation = commands.add_parser("validate")
    validation.add_argument("--queries", type=Path, required=True)
    validation.add_argument("--gold", type=Path)
    validation.add_argument("--extractions", type=Path)
    validation.add_argument("--input-dir", type=Path)
    validation.add_argument("--prior-queries", type=Path, action="append", default=[])
    prep = commands.add_parser("prepare")
    prep.add_argument("--queries", type=Path, required=True)
    prep.add_argument("--input-dir", type=Path, required=True)
    prep.add_argument("--output-dir", type=Path, required=True)
    sealing = commands.add_parser("seal")
    sealing.add_argument("--prepared", type=Path, required=True)
    sealing.add_argument("--gold", type=Path, required=True)
    sealing.add_argument("--output", type=Path, required=True)
    sealing.add_argument("--custodian", required=True)
    sealing.add_argument("--prior-queries", type=Path, action="append", default=[])
    sealing.add_argument("--max-chars", type=int, choices=[6000, 12000], default=6000)
    sealing.add_argument("--repeats", type=int, default=3)
    runner = commands.add_parser("run")
    runner.add_argument("--prepared", type=Path, required=True)
    runner.add_argument("--output-dir", type=Path, required=True)
    runner.add_argument("--repeats", type=int, default=3)
    runner.add_argument("--max-chars", type=int, choices=[6000, 12000], default=6000)
    runner.add_argument("--seal", type=Path)
    blinded = commands.add_parser("blind")
    blinded.add_argument("--run-dir", type=Path, required=True)
    blinded.add_argument("--output-dir", type=Path, required=True)
    blinded.add_argument("--private-key", type=Path, required=True)
    scorer = commands.add_parser("score")
    scorer.add_argument("--run-dir", type=Path, required=True)
    scorer.add_argument("--package", type=Path, required=True)
    scorer.add_argument("--private-key", type=Path, required=True)
    scorer.add_argument("--gold", type=Path, required=True)
    scorer.add_argument("--review", type=Path, action="append", required=True)
    scorer.add_argument("--adjudication", type=Path)
    scorer.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate":
        queries = read(args.queries)
        validate_queries(queries, [read(p) for p in args.prior_queries])
        if args.input_dir:
            validate_sources(queries, args.input_dir)
        if args.gold:
            validate_gold(
                args.queries, read(args.gold), read(args.extractions) if args.extractions else None
            )
        print(
            "Fixture valid; exact gold replay "
            + (
                "checked."
                if args.gold and args.extractions
                else "not checked (supply gold and extractions)."
            )
        )
    elif args.command == "prepare":
        asyncio.run(prepare(args.queries, args.input_dir, args.output_dir))
    elif args.command == "seal":
        seal(
            args.prepared,
            args.gold,
            args.output,
            args.custodian,
            args.prior_queries,
            args.max_chars,
            args.repeats,
        )
    elif args.command == "run":
        asyncio.run(
            run(args.prepared, args.output_dir, args.repeats, args.max_chars, seal_path=args.seal)
        )
    elif args.command == "blind":
        blind(args.run_dir, args.output_dir, args.private_key)
    elif args.command == "score":
        score(
            args.run_dir,
            args.package,
            args.private_key,
            args.gold,
            args.review,
            args.output,
            args.adjudication,
        )


if __name__ == "__main__":
    main()
