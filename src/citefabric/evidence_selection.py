"""Opt-in structured retrieval with bounded candidates and exact-span bundles.

No benchmark, reference answers, paper-specific entities or gold pages are loaded.
Lexical matches and region completeness are never semantic claim assessments.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from .models import EvidenceRequest
from .retrieval import (
    concept_coverage,
    quality_flags,
    query_plan,
    range_row,
    searchable_text,
    with_context,
)
from .storage import Store
from .structure import BUILDER_VERSION, ensure_index, stable_id


def bundles_for(rows: list[dict], hits: list[dict], plan: dict) -> list[dict]:
    """Group returned exact spans from one extraction; lexical roles are hints."""
    groups: dict[str, dict] = {}
    by_id = {row["id"]: row for row in rows}
    for hit in hits:
        evidence = hit["evidence"]
        row = by_id[evidence["evidence_id"]]
        group = groups.setdefault(
            evidence["extraction_id"],
            {
                "evidence_ids": [],
                "roles": {},
                "missing_requirements": [],
                "structure_status": "text_region; cells not verified",
                "requirements_status": "unassessed",
                "assessment_scope": "lexical retrieval roles only; not semantic verification",
            },
        )
        eid = evidence["evidence_id"]
        group["evidence_ids"].append(eid)
        text = searchable_text(evidence["excerpt"])
        roles = ["primary_candidate"]
        if "table" in row.get("kinds", []):
            roles.append("table_context")
        if "scope" in row.get("kinds", []) or re.search(
            r"no evidence|tests are consistent|upper bound", text
        ):
            roles.append("scope_candidate")
        if "training" in text:
            roles.append("training_context")
        if "inference" in text:
            roles.append("inference_context")
        group["roles"][eid] = roles
    for group in groups.values():
        observed = {role for roles in group["roles"].values() for role in roles}
        if plan.get("scope_requested") and "scope_candidate" not in observed:
            group["missing_requirements"].append("scope_context")
        if plan.get("comparison_requested") and not (
            plan.get("cost_requested") and {"training_context", "inference_context"} <= observed
        ):
            group["missing_requirements"].append("comparison_relationship_unassessed")
        if group["missing_requirements"]:
            group["requirements_status"] = "incomplete_or_unassessed"
        group["bundle_id"] = stable_id(
            "bundle-v1:" + plan["original"] + ":" + ":".join(group["evidence_ids"])
        )
    return list(groups.values())


STOP = set(
    "the a an is are of to and in does do that with on for we it as by be from what how which all no only than this these have has paper results main".split()
)


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9_]*|\d+(?:\.\d+)?", searchable_text(text)))


def plan_query(query: str, expand: bool) -> dict:
    plan = query_plan(query, expand)
    literals = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", query)
    entities = [
        x
        for x in literals
        if x.casefold() not in STOP
        and (re.search(r"\d|_|[a-z][A-Z]", x) or (x.isupper() and len(x) >= 3))
    ]
    plan["literal_terms"] = list(dict.fromkeys(x.casefold().replace("_", "") for x in entities))
    plan["reference_terms"] = [
        {"kind": "figure" if m[0].casefold().startswith("fig") else "table", "number": m[1]}
        for m in re.findall(r"(?i)\b(table|fig(?:ure)?\.?)\s*(\d+)\b", query)
    ]
    norm = searchable_text(query)
    plan["scope_requested"] = bool(
        re.search(
            r"任意|所有|保证|是否证明|是否能.*推出|all conditions|all future|guarantee|universally|always|limitations|no evidence",
            norm,
        )
    )
    plan["comparison_requested"] = bool(
        re.search(
            r"是否意味着|变化|训练.*推理|推理.*训练|compared|versus|no defense|overhead|training time",
            norm,
        )
    )
    plan["table_requested"] = bool(
        re.search(
            r"table|表格|表\s*\d|表中|bleu|\bmae|\bmse|误差变化|main results|median|中位数|sample size|样本量|复杂度|complexity",
            norm,
        )
    )
    plan["cost_requested"] = bool(
        re.search(r"开销|耗时|overhead|training time|training cost", norm)
    )
    if (
        re.search(
            r"能否判定|越大|越小|指标.*含义|指标.*定义|metric.*interpret|definition|higher.*better|lower.*better",
            norm,
        )
        and not plan["reference_terms"]
    ):
        plan["table_requested"] = False
    if re.search(r"所有数据集|all datasets", norm) and not re.search(
        r"任意未来|保证|guarantee", norm
    ):
        plan["scope_requested"] = False
    plan["requirements"] = ["primary_result"]
    if plan["scope_requested"]:
        plan["requirements"].append("scope_context")
    if plan["comparison_requested"]:
        plan["requirements"].append("comparison_context")
    return plan


def entity_matches(text: str, entities: list[str]) -> list[str]:
    words = tokens(text)
    aliases = {w.replace("_", "") for w in words}
    return [
        e
        for e in entities
        if e in aliases
        or (
            len(e) >= 4
            and re.search(
                r"\b" + r"[ \t]?".join(re.escape(c) for c in e) + r"\b", searchable_text(text)
            )
        )
    ]


def expression(text: str, *, conjunction: bool = False) -> str:
    words = [x for x in re.findall(r"\w+", searchable_text(text)) if x not in STOP][:64]
    return (" AND " if conjunction else " OR ").join('"' + x + '"' for x in dict.fromkeys(words))


def candidates(store: Store, index_ids: list[str], edition_id: str, plan: dict) -> list[dict]:
    selected: dict[str, dict] = {}
    placeholders = ",".join("?" for _ in index_ids)
    if not placeholders:
        return []

    def search(channel: str, kinds: list[str], query: str, limit: int, conjunction=False):
        expr = expression(query, conjunction=conjunction)
        if not expr:
            return
        kind_slots = ",".join("?" for _ in kinds)
        rows = store.db.execute(
            f"SELECT b.*,bm25(structure_fts) AS score FROM structure_fts JOIN structure_blocks b ON b.id=structure_fts.id WHERE structure_fts MATCH ? AND b.index_id IN ({placeholders}) AND b.kind IN ({kind_slots}) ORDER BY score,b.unit_id,b.start,b.end LIMIT ?",
            (expr, *index_ids, *kinds, limit),
        )
        for rank, item in enumerate(rows, 1):
            row = dict(item)
            row["channels"] = {channel: rank}
            if row["id"] in selected:
                selected[row["id"]]["channels"][channel] = rank
            else:
                selected[row["id"]] = row

    search("paragraph", ["paragraph"], plan["expanded"], 32)
    search(
        "page",
        ["page"],
        " ".join(plan["literal_terms"]) or plan["expanded"],
        12,
        bool(plan["literal_terms"]),
    )
    search("table", ["table", "table_ambiguous", "figure"], plan["expanded"], 12)
    special = plan["scope_requested"] or plan["cost_requested"]
    search("context", ["scope", "qualifier"] if special else ["qualifier"], plan["expanded"], 8)
    # Named limitations can have none of a universal claim's exact query words.
    # This is an explicit, bounded scope lookup within the already selected edition.
    if plan["scope_requested"]:
        search(
            "scope_followup", ["scope", "qualifier"], "limitations no evidence tests consistent", 12
        )
    if plan["cost_requested"]:
        search(
            "cost_followup", ["qualifier", "paragraph"], "training inference overhead time cost", 12
        )
    if plan["literal_terms"]:
        search(
            "entity_followup",
            ["table", "figure"],
            " ".join(plan["literal_terms"]),
            48,
            True,
        )
    if plan["cost_requested"] or plan["table_requested"] or plan["comparison_requested"]:
        leaders = sorted(selected.values(), key=lambda r: tuple(-x for x in features(r, plan)))[:4]
        references = list(
            dict.fromkeys(
                number
                for r in leaders
                for number in re.findall(r"(?i)\btable\s*(\d+)\b", r["text"])
            )
        )[:4]
        for number in references:
            search("reference:" + number, ["table"], "Table " + number, 6, True)
            for found in selected.values():
                if found["kind"] == "table" and re.match(
                    r"(?i)^\s*Table\s*" + number + r"\b", found["text"]
                ):
                    found["reference_priority"] = 1
    # All channels combined remain below 128 unique candidates per edition.
    rows = list(selected.values())[:128]
    for row in rows:
        row["edition_id"] = edition_id
    return rows


def features(row: dict, plan: dict) -> tuple:
    text = searchable_text(row["text"])
    matches = entity_matches(text, plan["literal_terms"])
    entity_fraction = len(matches) / len(plan["literal_terms"]) if plan["literal_terms"] else 0
    relevant = tokens(plan["expanded"]) - STOP
    lexical = len(tokens(text) & relevant) / max(1, len(relevant))
    concept = concept_coverage(text, plan)
    is_table = row["kind"] == "table"
    # Region co-occurrence precedes broad page co-occurrence.
    entity_rank = entity_fraction * (0.9 if row["kind"] == "page" else 1.0)
    intent = -0.15 if row["kind"] == "page" else 0.0
    if plan["table_requested"] and is_table:
        intent += 0.25
        if "main results" in text or "averaged across" in text:
            intent += 0.1
    if plan["scope_requested"]:
        if row["kind"] == "scope":
            intent += 0.65
        elif row["kind"] == "qualifier" and re.search(
            r"no evidence|tests are consistent|upper bound", text
        ):
            intent += 0.6
    if plan["cost_requested"]:
        train = "training" in text
        inference = "inference" in text
        intent += 0.25 * train + 0.25 * inference
        intent += 0.25 * bool(train and inference)
    quality = -0.3 if "bibliography_like" in quality_flags(text) else 0
    fusion = sum(1 / (60 + rank) for rank in row["channels"].values())
    reference = 0
    for ref in plan["reference_terms"]:
        pattern = (
            (r"\bfig(?:ure)?\.?\s*" if ref["kind"] == "figure" else r"\btable\s*")
            + re.escape(ref["number"])
            + r"\b"
        )
        if re.search(pattern, text):
            reference += 2 if row["kind"] == ref["kind"] else 1
    role_priority = 0
    if plan["scope_requested"] and (
        row["kind"] == "scope"
        or (
            row["kind"] == "qualifier"
            and re.search(r"no evidence|tests are consistent|upper bound", text)
        )
    ):
        role_priority = 1
    if (
        plan["cost_requested"]
        and re.search(r"no inference[-\s]+time overhead", text)
        and row["kind"] != "page"
    ):
        role_priority = 1
    if (
        plan["cost_requested"]
        and row["kind"] == "table"
        and row.get("reference_priority")
        and re.search(r"training|inference|time|cost|overhead", text)
    ):
        role_priority = 2
    return (
        reference,
        role_priority,
        entity_rank,
        lexical + 0.4 * concept + intent + quality,
        fusion,
    )


def as_evidence_row(row: dict) -> dict:
    return dict(
        row,
        id=stable_id(
            f"structured-span-v1:{row['extraction_id']}:{row['unit_id']}:{row['start']}:{row['end']}"
        ),
        seed_ids=list(dict.fromkeys(row.get("member_block_ids", [row["id"]]))),
    )


def select(
    store: Store, rows: list[dict], plan: dict, request: EvidenceRequest
) -> tuple[list[dict], dict]:
    ranked = sorted(
        rows,
        key=lambda r: (
            *(-x for x in features(r, plan)),
            r["edition_id"],
            r["unit_id"],
            r["start"],
            r["end"],
        ),
    )
    chosen: list[dict] = []
    dropped = []
    size = 0
    per_edition: dict[str, int] = {}
    used = set()
    units: dict[tuple[str, str], str] = {}

    def raw(row):
        key = (row["extraction_id"], row["unit_id"])
        if key not in units:
            units[key] = next(
                u.text for u in store.extraction(key[0]).text_units if u.text_unit_id == key[1]
            )
        return units[key]

    def contextual(row):
        row = dict(row, member_block_ids=[row["id"]], kinds=[row["kind"]])
        if not request.include_context or row["kind"] == "page":
            return row
        # Include an intersecting table as one contiguous raw region; preserve all
        # intervening source text, and fall back explicitly if it cannot fit.
        related = [
            r
            for r in rows
            if r["kind"] == "table"
            and (r["extraction_id"], r["unit_id"]) == (row["extraction_id"], row["unit_id"])
            and r["start"] < row["end"]
            and row["start"] < r["end"]
        ]
        if related:
            row["start"] = min([row["start"], *[r["start"] for r in related]])
            row["end"] = max([row["end"], *[r["end"] for r in related]])
            row["member_block_ids"] += [r["id"] for r in related]
            row["kinds"] += [r["kind"] for r in related]
            row["text"] = raw(row)[row["start"] : row["end"]]
        return row

    # Give each edition a first region before allocating remaining slots. A
    # candidate overlapping existing evidence extends that exact raw range.
    for cap in (1, request.max_passages):
        for seed in ranked:
            if seed["id"] in used:
                continue
            if per_edition.get(seed["edition_id"], 0) >= cap:
                continue
            if not request.include_context and seed["kind"] != "paragraph":
                continue
            if chosen and seed["kind"] == "page":
                continue
            if seed["kind"] in {"scope", "future"} and len(seed["text"].strip()) < 80:
                continue
            row = contextual(seed)
            overlaps = [
                r
                for r in chosen
                if (r["extraction_id"], r["unit_id"]) == (row["extraction_id"], row["unit_id"])
                and r["start"] <= row["end"]
                and row["start"] <= r["end"]
            ]
            if overlaps:
                row["start"] = min([row["start"], *[r["start"] for r in overlaps]])
                row["end"] = max([row["end"], *[r["end"] for r in overlaps]])
                row["text"] = raw(row)[row["start"] : row["end"]]
                row["member_block_ids"] += [bid for r in overlaps for bid in r["member_block_ids"]]
                row["kinds"] += [k for r in overlaps for k in r["kinds"]]
            cost = len(row["text"]) - sum(len(r["text"]) for r in overlaps)
            if (
                size + cost > request.max_chars
                or len(chosen) + 1 - len(overlaps) > request.max_passages
            ):
                dropped.append(seed["id"])
                continue
            used.add(seed["id"])
            if cost == 0:
                continue
            chosen = [r for r in chosen if r not in overlaps]
            chosen.append(row)
            size += cost
            per_edition[row["edition_id"]] = sum(
                r["edition_id"] == row["edition_id"] for r in chosen
            )
    scope_covered = any(
        "scope" in row["kinds"]
        or re.search(r"no evidence|tests are consistent|upper bound", searchable_text(row["text"]))
        for row in chosen
    )
    missing = []
    if not chosen:
        missing.append("primary_result")
    if plan["scope_requested"] and (not scope_covered or not request.include_context):
        missing.append("scope_context")
    matched = {e for row in chosen for e in entity_matches(row["text"], plan["literal_terms"])}
    missing += ["literal:" + e for e in plan["literal_terms"] if e not in matched]
    trace = {
        "candidate_count": len(rows),
        "candidate_limited": True,
        "returned_chars": size,
        "returned_passages": len(chosen),
        "budget_rejected_candidates": len(set(dropped)),
        "missing_requirements": missing,
        "condition_coverage": [
            {
                "literal": e,
                "status": "matched_in_returned_text; relation_unassessed"
                if any(entity_matches(r["text"], [e]) for r in chosen)
                else "not_found_in_returned_evidence",
            }
            for e in plan["literal_terms"]
        ],
        "context_policy": "role-regions-v1" if request.include_context else "disabled",
        "ranked_candidates": [
            {
                "block_id": r["id"],
                "unit_id": r["unit_id"],
                "kind": r["kind"],
                "features": features(r, plan),
                "channels": r["channels"],
            }
            for r in ranked[:20]
        ],
    }
    return [as_evidence_row(row) for row in chosen], trace


async def retrieve(
    store: Store, edition_ids: list[str], request: EvidenceRequest
) -> tuple[list[dict[str, Any]], dict]:
    plan = plan_query(request.query, request.expand_query)
    rows = []
    indexes = []
    # Retain the established lexical route for ordinary explanatory queries;
    # structural selection is specifically for tables, comparisons and scope.
    if not (
        plan["table_requested"]
        or plan["scope_requested"]
        or plan["cost_requested"]
        or plan["reference_terms"]
    ):
        seeds = store.passage_search(edition_ids, plan["expanded"])
        if plan["mappings"]:
            seeds.sort(key=lambda r: (-concept_coverage(r["text"], plan), r["score"], r["id"]))
        selected: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        size = 0
        for row in seeds:
            if (
                counts.get(row["edition_id"], 0) >= 4
                or len(selected) >= request.max_passages
                or size + len(row["text"]) > request.max_chars
            ):
                continue
            if (
                not request.allow_abstract
                and store.extraction(row["extraction_id"]).coverage.source_kind == "abstract"
            ):
                continue
            selected.append(row)
            size += len(row["text"])
            counts[row["edition_id"]] = counts.get(row["edition_id"], 0) + 1
        seed_selection = list(selected)
        compact_budget = min(request.max_chars, 6000)
        if request.include_context:
            selected = with_context(store, selected, compact_budget)
        for row in selected:
            row["origin"] = "passage"
        reference_edges = []
        missing_edges = []
        if request.include_context:
            # A compact passage that explicitly cites a table may need that table
            # even when the user asks an ordinary explanatory question.
            async with asyncio.timeout(10):
                for parent in seeds[:4]:
                    if not any(
                        r["extraction_id"] == parent["extraction_id"]
                        and r["unit_id"] == parent["unit_id"]
                        and r["start"] <= parent["start"]
                        and r["end"] >= parent["end"]
                        for r in selected
                    ):
                        continue
                    numbers = list(
                        dict.fromkeys(re.findall(r"(?i)\btable\s*(\d+)\b", parent["text"]))
                    )[:2]
                    if not numbers:
                        continue
                    index_id = await ensure_index(
                        store, store.extraction(parent["extraction_id"]), parent["edition_id"]
                    )
                    indexes.append(index_id)
                    blocks = store.db.execute(
                        "SELECT * FROM structure_blocks WHERE index_id=? AND kind='table' ORDER BY unit_id,start LIMIT 128",
                        (index_id,),
                    ).fetchall()
                    for number in numbers:
                        target = next(
                            (
                                dict(b)
                                for b in blocks
                                if re.match(r"(?i)^\s*Table\s*" + number + r"\b", b["text"])
                            ),
                            None,
                        )
                        if target is None:
                            continue
                        key = (target["extraction_id"], target["unit_id"])
                        if any(
                            (r["extraction_id"], r["unit_id"]) == key
                            and r["start"] <= target["start"]
                            and r["end"] >= target["end"]
                            for r in selected
                        ):
                            continue
                        child = as_evidence_row(
                            dict(
                                target,
                                score=parent["score"],
                                kinds=["table"],
                                score_basis="referring_passage_bm25; not semantic confidence",
                            )
                        )
                        proposal = selected + [child]
                        while proposal and (
                            sum(len(r["text"]) for r in proposal) > compact_budget
                            or len(proposal) > request.max_passages
                        ):
                            # Shrink optional page expansion before discarding a
                            # directly matched seed. This preserves primary evidence.
                            variants = []
                            for i, item in enumerate(proposal):
                                anchors = [
                                    r
                                    for r in seed_selection
                                    if (r["extraction_id"], r["unit_id"])
                                    == (item["extraction_id"], item["unit_id"])
                                    and item["start"] <= r["start"]
                                    and item["end"] >= r["end"]
                                ]
                                if item.get("origin") == "passage" and anchors:
                                    left, right = (
                                        min(r["start"] for r in anchors),
                                        max(r["end"] for r in anchors),
                                    )
                                    saving = len(item["text"]) - (right - left)
                                    if saving > 0:
                                        variants.append((saving, i, left, right))
                            if variants:
                                _, i, left, right = max(variants)
                                proposal[i] = range_row(store, proposal[i], left, right)
                                continue
                            # Keep previously accepted dependencies and all
                            # primary seeds. Additional references may use the
                            # caller's larger budget, or remain explicitly missing.
                            break
                        if (
                            sum(len(r["text"]) for r in proposal) <= request.max_chars
                            and len(proposal) <= request.max_passages
                        ):
                            selected = proposal
                            reference_edges.append(
                                {
                                    "referring_passage_id": parent["id"],
                                    "target_block_id": target["id"],
                                }
                            )
                        else:
                            missing_edges.append(
                                {
                                    "referring_passage_id": parent["id"],
                                    "target_block_id": target["id"],
                                    "reason": "context_budget_exceeded",
                                }
                            )
        active_blocks = {bid for row in selected for bid in row.get("seed_ids", [row["id"]])}
        reference_edges = [
            edge for edge in reference_edges if edge["target_block_id"] in active_blocks
        ]
        return selected, {
            "query_plan": plan,
            "structure_index_version": BUILDER_VERSION,
            "structure_index_ids": list(dict.fromkeys(indexes)),
            "selection_trace": {
                "route": "lexical_compatibility",
                "reference_edges": reference_edges,
                "missing_reference_edges": missing_edges,
                "budget_relaxed": sum(len(r["text"]) for r in selected) > compact_budget,
                "requested_max_chars": request.max_chars,
                "compact_max_chars": compact_budget,
                "candidate_count": len(seeds),
                "candidate_limited": True,
                "budget_rejected_candidates": len(missing_edges),
                "returned_chars": sum(len(r["text"]) for r in selected),
                "returned_passages": len(selected),
                "missing_requirements": ["referenced_context"] if missing_edges else [],
                "context_policy": "same-page-bounded-v1" if request.include_context else "disabled",
            },
        }
    async with asyncio.timeout(10):
        for edition_id in dict.fromkeys(edition_ids):
            ids = []
            for doc in store.documents(edition_id):
                if doc.source_kind == "abstract" and not request.allow_abstract:
                    continue
                for item in store.db.execute(
                    "SELECT id FROM extractions WHERE document_id=?", (doc.document_id,)
                ).fetchall():
                    ids.append(await ensure_index(store, store.extraction(item[0]), edition_id))
            indexes.extend(ids)
            rows.extend(candidates(store, ids, edition_id, plan))
    compact = request.model_copy(update={"max_chars": min(request.max_chars, 6000)})
    selected, trace = select(store, rows, plan, compact)
    trace["requested_max_chars"] = request.max_chars
    trace["compact_max_chars"] = compact.max_chars
    trace["budget_relaxed"] = False
    if trace["missing_requirements"] and request.max_chars > compact.max_chars:
        selected, expanded_trace = select(store, rows, plan, request)
        expanded_trace.update(
            requested_max_chars=request.max_chars,
            compact_max_chars=compact.max_chars,
            budget_relaxed=True,
        )
        trace = expanded_trace
    if rows and not selected and trace["budget_rejected_candidates"]:
        trace["outcome_code"] = "context_budget_exceeded"
    return selected, {
        "query_plan": plan,
        "selection_trace": trace,
        "structure_index_version": BUILDER_VERSION,
        "structure_index_ids": indexes,
    }
