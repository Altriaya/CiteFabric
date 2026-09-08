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


def searchable_text(text: str) -> str:
    return unicodedata.normalize("NFKC", re.sub(r"-\s*\n\s*", "", text)).casefold()


def query_plan(query: str, enabled: bool = True) -> dict[str, Any]:
    mappings = []
    normalized = unicodedata.normalize("NFKC", query)
    if enabled:
        for phrase, english in GLOSSARY.items():
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
