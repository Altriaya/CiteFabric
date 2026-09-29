"""Auditable lexical query expansion and bounded, same-page evidence context.

The glossary bridges common research vocabulary, not arbitrary Chinese translation.
Nothing here loads benchmark questions, paper names, answers or reference pages.
Search normalization never changes the stored extraction or evidence offsets.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

if TYPE_CHECKING:
    from .storage import Store


GLOSSARY = {
    "网络结构": "architecture",
    "框架": "framework",
    "方法": "method methods",
    "模型": "model models",
    "变量": "variable variables",
    "关系": "correlation correlations",
    "触发器": "trigger triggers",
    "数据集": "dataset datasets",
    "划分": "split splits",
    "误差": "error errors",
    "指标": "metrics metric",
    "攻击": "attack attacks",
    "平均": "average mean",
    "中位数": "median",
    "分数": "score scores",
    "结果": "results",
    "改善": "improve improves",
    "干净": "clean",
    "预测": "prediction forecasting",
    "异常检测": "anomaly detection",
    "准确率": "accuracy",
    "精度": "accuracy",
    "训练": "training",
    "测试集": "test",
    "开发集": "development",
    "开销": "overhead cost",
    "耗时": "time",
    "效率": "efficiency",
    "推理": "inference",
    "限制": "limitations",
    "未来": "future",
    "跨领域": "transferability",
    "多目标": "multiple multi",
    "异步": "asynchronous",
    "延迟": "delayed delay",
    "位置": "position positional",
    "参考集": "reference",
    "可靠池": "reliable pool",
    "并集": "union",
    "交集": "intersect intersection",
    "置信": "confidence",
    "不确定": "uncertainties uncertainty",
    "区间": "interval intervals",
    "样本量": "sample samples",
    "信号": "signal",
    "匹配滤波": "matched filter filtering",
    "虚警率": "false alarm rate",
    "上界": "upper bound",
    "显著性": "significance",
    "观测": "observed observation",
    "概率": "probability",
    "复杂度": "complexity",
    "临床": "clinical",
    "患者": "patient patients",
    "试验": "trial trials",
    "医院": "hospital",
    "防御": "defense defenses",
    "评估": "evaluation evaluate",
    "问题": "issues challenges",
    "循环": "recurrent recurrence",
    "卷积": "convolution convolutions",
    "函数": "function functions",
    "学习": "learned learning",
    "基础": "base",
    "大型": "big",
    "表格": "table",
    "图注": "figure",
}


# Candidate v5 vocabulary is kept separate so replaying offline_structured_v4
# continues to use its frozen query plan.  Antonym/set-operation pairs are
# intentionally symmetric: a false claim often contains the opposite term from
# the source passage, and retrieval must surface that passage for verification.
MATERIAL_GLOSSARY = {
    "双层": "bi-level bilevel",
    "优化": "optimization",
    "生成器": "generator",
    "训练损失": "training loss",
    "损失": "loss",
    "退化": "degradation",
    "信号稀释": "signal dilution",
    "通道": "channel channels",
    "注意力": "attention",
    "骨架": "backbone",
    "蛋白质": "protein",
    "结构域": "domain domains",
    "残基": "residue residues",
    "样本": "sample samples",
    "越大": "higher lower larger smaller",
    "越小": "lower higher smaller larger",
    "并集": "union intersect intersection",
    "交集": "intersect intersection union",
}


def searchable_text(text: str) -> str:
    return unicodedata.normalize("NFKC", re.sub(r"-\s*\n\s*", "", text)).casefold()


def query_plan(
    query: str, enabled: bool = True, extra_glossary: dict[str, str] | None = None
) -> dict[str, Any]:
    mappings = []
    normalized = unicodedata.normalize("NFKC", query)
    if enabled:
        glossary = dict(GLOSSARY)
        glossary.update(extra_glossary or {})
        for phrase, english in glossary.items():
            if phrase in normalized:
                mappings.append({"source": phrase, "terms": english.split()})
    aliases = []
    if enabled:
        # MAE_A / MAEₐ and similar metric spellings often become MAEA in PDF text.
        for token in re.findall(r"[A-Za-z]+(?:_[A-Za-z0-9]+)+", normalized):
            aliases.append(token.replace("_", ""))
    terms = list(dict.fromkeys(t for item in mappings for t in item["terms"]))
    expanded = " ".join([normalized if enabled else query, *aliases, *terms])
    return {
        "original": query,
        "expanded": expanded,
        "method": "research-glossary-zh-en-v1" if mappings else "lexical",
        "mappings": mappings,
        "metric_aliases": aliases,
        "contains_chinese": bool(re.search(r"[\u3400-\u9fff]", query)),
        "semantic_translation": False,
    }


_SCOPE_MARKERS = (
    "任意",
    "所有",
    "保证",
    "是否证明",
    "是否能推出",
    "限制",
    "不能说明",
)
_TABLE_MARKERS = ("表格", "表中", "表 ")
_MATERIAL_CONDITION_MARKERS = (
    "并集",
    "交集",
    "同时",
    "分别",
    "提升至",
    "下降至",
    "高于",
    "低于",
    "越大",
    "越小",
)

_SMALL_NUMBER_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
    "10": "ten",
    "11": "eleven",
    "12": "twelve",
    "13": "thirteen",
    "14": "fourteen",
    "15": "fifteen",
    "16": "sixteen",
    "17": "seventeen",
    "18": "eighteen",
    "19": "nineteen",
    "20": "twenty",
}


def offline_structured_plan(
    query: str,
    enabled: bool = True,
    *,
    material_channels: bool = False,
    safe_material_routing: bool = False,
) -> dict[str, Any]:
    """Plan bounded, separately ranked local lexical channels.

    This is deliberately a query planner, not a translator.  Chinese text stays
    in its own channel for locally imported Chinese papers; glossary terms and
    ASCII literals are searched separately so they cannot distort its rank.
    """
    plan = query_plan(query, enabled, MATERIAL_GLOSSARY if material_channels else None)
    normalized = unicodedata.normalize("NFKC", query)
    english_terms = list(dict.fromkeys(t for item in plan["mappings"] for t in item["terms"]))
    literals = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", normalized)
    entity_terms = list(
        dict.fromkeys(
            token.replace("_", "")
            for token in literals
            if len(token) >= 3 and (token.isupper() or re.search(r"\d|_", token))
        )
    )
    lowered = searchable_text(normalized)
    scope_requested = any(marker in normalized for marker in _SCOPE_MARKERS) or bool(
        re.search(
            r"all conditions|all future|guarantee|universally|limitations|cannot conclude", lowered
        )
    )
    # A broad numeric question is not proof that its answer is in a table.  The
    # table channel therefore requires an explicit table reference; metric/table
    # completeness is evaluated in a separate later experiment.
    table_requested = any(marker in normalized for marker in _TABLE_MARKERS) or bool(
        re.search(r"\btable\s*\d", lowered)
    )
    numeric_terms: list[str] = []
    numeric_aliases: dict[str, list[str]] = {}
    reference_terms: list[dict[str, str]] = []
    if material_channels:
        # Commas in thousands separators are removed because PDF extraction and
        # SQLite tokenization do not represent them consistently.  Single digit
        # numbers are handled only as explicit Table/Figure references to avoid
        # a large, noisy numeric channel.
        numeric_source = normalized.replace(",", "")
        numeric_terms = list(
            dict.fromkeys(
                token
                for token in re.findall(r"(?<![\w.])\d+(?:\.\d+)?%?", numeric_source)
                if "." in token or len(token.rstrip("%")) >= 2
            )
        )
        numeric_aliases = {
            term: [_SMALL_NUMBER_WORDS[term]]
            for term in numeric_terms
            if term in _SMALL_NUMBER_WORDS
        }
        references = [
            *(("table", number) for number in re.findall(r"表\s*(\d+[A-Za-z]?)", normalized)),
            *(("figure", number) for number in re.findall(r"图\s*(\d+[A-Za-z]?)", normalized)),
            *(
                (
                    "table" if kind.casefold() == "table" else "figure",
                    number,
                )
                for kind, number in re.findall(
                    r"\b(table|fig(?:ure)?\.?)\s*(\d+[A-Za-z]?)", normalized, re.I
                )
            ),
        ]
        reference_terms = [
            {"kind": kind, "number": number} for kind, number in dict.fromkeys(references)
        ]
    quantitative_terms = [
        term
        for term in numeric_terms
        if not (term.isdigit() and len(term) == 4 and 1800 <= int(term) <= 2199)
    ]
    joint_requested = material_channels and (
        any(marker in normalized for marker in _MATERIAL_CONDITION_MARKERS)
        or bool(
            re.search(
                r"\b(?:both|respectively|union|intersection|higher than|lower than)\b",
                lowered,
            )
        )
    )
    material_signal = bool(quantitative_terms or reference_terms or joint_requested)
    channels: list[dict[str, Any]] = [
        {"id": "original", "query": normalized, "limit": 32, "role": "native_language"}
    ]
    if english_terms:
        channels.append(
            {
                "id": "bilingual_glossary",
                "query": " ".join(english_terms),
                "limit": 32,
                "role": "glossary_terms",
            }
        )
    for term in entity_terms[:8]:
        channels.append(
            {"id": "entity:" + term, "query": term, "limit": 12, "role": "exact_entity"}
        )
    if numeric_terms:
        numeric_query_terms = [
            term for number in numeric_terms for term in [number, *numeric_aliases.get(number, [])]
        ]
        channels.append(
            {
                "id": "numeric_bundle",
                "query": " ".join(numeric_query_terms),
                "limit": 24,
                "role": "exact_numeric",
            }
        )
    for reference in reference_terms[:4]:
        label = "table" if reference["kind"] == "table" else "fig figure"
        channels.append(
            {
                "id": f"reference:{reference['kind']}:{reference['number']}",
                "query": f"{label} {reference['number']}",
                "limit": 16,
                "role": "exact_reference",
            }
        )
    if table_requested:
        channels.append(
            {"id": "table_context", "query": "table results", "limit": 12, "role": "table_context"}
        )
    if scope_requested:
        channels.append(
            {
                "id": "scope_context",
                "query": "limitations scope no evidence cannot conclude guarantee",
                "limit": 12,
                "role": "scope_context",
            }
        )
    plan.update(
        {
            "method": (
                "offline-safe-material-route-v6"
                if safe_material_routing
                else "offline-material-channels-v5"
                if material_channels
                else "offline-structured-channels-v4"
            ),
            "channels": channels,
            "entity_terms": entity_terms,
            "numeric_terms": numeric_terms,
            "numeric_aliases": numeric_aliases,
            "quantitative_terms": quantitative_terms,
            "reference_terms": reference_terms,
            "material_channels": material_channels,
            "material_signal": material_signal,
            "joint_requested": joint_requested,
            "front_matter_tiebreak": material_channels and not safe_material_routing,
            "scope_requested": scope_requested,
            "table_requested": table_requested,
            "semantic_translation": False,
        }
    )
    return plan


def offline_structured_candidates(
    store: Store, edition_ids: list[str], plan: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fuse fixed-cap lexical channels using reciprocal-rank fusion.

    Each query is issued independently.  The returned trace records the exact
    queries and hit counts, making the local-only experiment replayable.
    """
    selected: dict[str, dict[str, Any]] = {}
    trace: list[dict[str, Any]] = []
    for channel in plan["channels"]:
        rows = store.passage_search(edition_ids, channel["query"], limit=channel["limit"])
        trace.append(
            {
                "id": channel["id"],
                "role": channel["role"],
                "query": channel["query"],
                "limit": channel["limit"],
                "candidates": len(rows),
            }
        )
        for rank, source in enumerate(rows, 1):
            row = selected.setdefault(source["id"], dict(source, channels={}))
            row["channels"][channel["id"]] = rank
    for row in selected.values():
        text = searchable_text(row["text"])
        entity_hits = sum(
            bool(re.search(r"\b" + re.escape(entity.casefold()) + r"\b", text))
            for entity in plan["entity_terms"]
        )
        table_bonus = 0.025 if plan["table_requested"] and "table" in text else 0.0
        scope_bonus = (
            0.025
            if plan["scope_requested"]
            and re.search(
                r"limitations?|no evidence|cannot conclude|consistent with|upper bound", text
            )
            else 0.0
        )
        numeric_hits = sum(
            any(
                re.search(r"(?<![\w.])" + re.escape(form.casefold()) + r"(?![\w.])", text)
                for form in [number, *plan.get("numeric_aliases", {}).get(number, [])]
            )
            for number in plan.get("numeric_terms", [])
        )
        reference_hits = sum(
            bool(
                re.search(
                    (r"\btable\s*" if reference["kind"] == "table" else r"\b(?:fig(?:ure)?\.?)\s*")
                    + re.escape(reference["number"].casefold())
                    + r"\b",
                    text,
                )
            )
            for reference in plan.get("reference_terms", [])
        )
        reference_heading_hits = sum(
            bool(
                re.search(
                    (r"\btable\s*" if reference["kind"] == "table" else r"\b(?:fig(?:ure)?\.?)\s*")
                    + re.escape(reference["number"].casefold())
                    + r"\b",
                    text[:200],
                )
            )
            for reference in plan.get("reference_terms", [])
        )
        mapping_coverage = (
            concept_coverage(row["text"], plan) if plan.get("material_channels") else 0
        )
        page_match = re.fullmatch(r"page:(\d+)", row["unit_id"])
        # Contribution summaries and abstracts are concentrated in front matter.
        # Use this only as a bounded tie-breaker; exact entities, numbers, and
        # explicit table/figure references still carry larger combined weight.
        front_matter_bonus = (
            0.04 / max(1, int(page_match.group(1)))
            if plan.get("front_matter_tiebreak") and page_match
            else 0.0
        )
        rrf = sum(1 / (60 + rank) for rank in row["channels"].values())
        row["rrf_score"] = (
            rrf
            + 0.035 * entity_hits
            + table_bonus
            + scope_bonus
            + 0.04 * numeric_hits
            + 0.06 * reference_hits
            + 0.08 * reference_heading_hits
            + 0.10 * mapping_coverage
            + front_matter_bonus
        )
        # Existing response code represents better results with a lower BM25 score.
        row["score"] = -row["rrf_score"]
        row["score_basis"] = (
            "material_channel_rrf-v3; lexical only, not semantic confidence"
            if plan.get("material_channels") and not plan.get("front_matter_tiebreak")
            else "material_channel_rrf-v2; lexical only, not semantic confidence"
            if plan.get("material_channels")
            else "bounded_channel_rrf-v1; lexical only, not semantic confidence"
        )
    return list(selected.values()), trace


def with_material_context(store: Store, seeds: list[dict], max_chars: int) -> list[dict]:
    """Pack complete top-ranked pages before lower-ranked passage fragments.

    Material claims commonly join a table heading, row labels, values, and
    qualifiers that span several passage windows.  The v5 policy spends the
    bounded character budget on the best candidate's complete page when it
    fits, then appends non-duplicate seed passages while capacity remains.
    """
    if not seeds:
        return []
    packed: list[dict[str, Any]] = []
    used_groups: set[tuple[str, str]] = set()
    used_chars = 0
    for seed in seeds:
        group = (seed["extraction_id"], seed["unit_id"])
        if group in used_groups:
            continue
        candidate = dict(seed, seed_ids=[seed["id"]])
        unit = next(
            u
            for u in store.extraction(seed["extraction_id"]).text_units
            if u.text_unit_id == seed["unit_id"]
        )
        if not packed and unit.page is not None:
            if len(unit.text) <= max_chars:
                start, end = 0, len(unit.text)
            else:
                # Keep the best seed inside the widest possible same-page
                # window.  Anchoring the window to a page edge avoids losing a
                # heading or qualifier when the page barely exceeds budget.
                start = min(seed["start"], len(unit.text) - max_chars)
                end = start + max_chars
            candidate = range_row(store, seed, start, end)
            candidate["seed_ids"] = [seed["id"]]
        if used_chars + len(candidate["text"]) > max_chars:
            continue
        packed.append(candidate)
        used_groups.add(group)
        used_chars += len(candidate["text"])
    return packed


def concept_coverage(text: str, plan: dict) -> float:
    """Rank lexical concepts separately from repeated paper-name matches."""
    words = set(re.findall(r"\w+", searchable_text(text)))
    matched = 0.0
    total = 0.0
    for item in plan["mappings"]:
        weight = 0.25 if item["source"] in {"模型", "方法", "结果", "问题"} else 1.0
        total += weight
        matched += weight * any(term in words for term in item["terms"])
    return matched / total if total else 0.0


def quality_flags(text: str) -> list[str]:
    flags = []
    if re.search(r"/uni[0-9a-f]{6,}|/C\d{3}", text, re.I) or "\ufffd" in text:
        flags.append("suspicious_pdf_glyphs")
    if re.search(r"(?:\bTable\s+\d|\bTABLE\s+[IVX]+)", text):
        flags.append("table_layout_requires_visual_review")
    if re.search(r"\d\.\d{2,}\d\.\d", text):
        flags.append("possibly_joined_numeric_cells")
    if re.search(r"\d[þ¼]", text):
        flags.append("scientific_symbol_encoding_uncertain")
    if len(re.findall(r"(?m)^\[\d+\]", text)) >= 3:
        flags.append("bibliography_like")
    return flags


def range_row(store: Store, row: dict, start: int, end: int) -> dict:
    unit = next(
        u
        for u in store.extraction(row["extraction_id"]).text_units
        if u.text_unit_id == row["unit_id"]
    )
    if (start, end) == (row["start"], row["end"]):
        return row
    identifier = str(
        uuid5(
            NAMESPACE_URL,
            f"citefabric:context-v1:{row['extraction_id']}:{row['unit_id']}:{start}:{end}",
        )
    )
    return dict(row, id=identifier, start=start, end=end, text=unit.text[start:end])


def with_context(store: Store, seeds: list[dict], max_chars: int) -> list[dict]:
    """Expand exact spans without exceeding the original request's total budget.

    Prefer context for table-bearing candidates. Try a short complete page first,
    then neighboring passage ranges. Never cross an extraction/page boundary or
    replace an existing immutable evidence object. Coalesce overlapping ranges.
    """
    selected = [dict(row, seed_ids=[row["id"]]) for row in seeds]

    def coalesce(rows: list[dict]) -> list[dict]:
        merged: list[dict] = []
        for row in rows:
            for i, previous in enumerate(merged):
                if (
                    (row["extraction_id"], row["unit_id"])
                    == (previous["extraction_id"], previous["unit_id"])
                    and row["start"] <= previous["end"]
                    and previous["start"] <= row["end"]
                ):
                    combined = range_row(
                        store,
                        previous,
                        min(previous["start"], row["start"]),
                        max(previous["end"], row["end"]),
                    )
                    combined["seed_ids"] = list(
                        dict.fromkeys(previous["seed_ids"] + row["seed_ids"])
                    )
                    merged[i] = combined
                    break
            else:
                merged.append(row)
        return coalesce(merged) if len(merged) < len(rows) else merged

    selected = coalesce(selected)
    priorities = sorted(
        [seed for row in selected for seed in row["seed_ids"]],
        key=lambda seed: (
            not any(
                seed in r["seed_ids"]
                and "table_layout_requires_visual_review" in quality_flags(r["text"])
                for r in selected
            )
        ),
    )
    processed = set()
    for seed in priorities:
        index = next((i for i, r in enumerate(selected) if seed in r["seed_ids"]), None)
        if index is None:
            continue
        row = selected[index]
        group = (row["extraction_id"], row["unit_id"])
        if group in processed:
            continue
        processed.add(group)
        neighbors = [
            dict(r)
            for r in store.db.execute(
                "SELECT * FROM passages WHERE extraction_id=? AND unit_id=? ORDER BY start", group
            )
        ]
        unit = next(u for u in store.extraction(group[0]).text_units if u.text_unit_id == group[1])
        before = [r for r in neighbors if r["start"] < row["start"]]
        after = [r for r in neighbors if r["end"] > row["end"]]
        left = before[-1]["start"] if before else row["start"]
        right = after[0]["end"] if after else row["end"]
        ranges = [(0, len(unit.text))] if unit.page is not None and len(unit.text) <= 6000 else []
        ranges += [(left, right), (row["start"], right), (left, row["end"])]
        for start, end in ranges:
            proposal = selected.copy()
            proposal[index] = range_row(store, row, start, end)
            proposal = coalesce(proposal)
            if sum(len(r["text"]) for r in proposal) <= max_chars:
                selected = proposal
                break
    return selected
