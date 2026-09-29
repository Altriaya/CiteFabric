"""Auditable, opt-in query rewriting for cross-language retrieval experiments.

This module deliberately has no model SDK dependency.  A caller supplies a
rewriter so the product can record its model and prompt revision, and can fall
back safely when no approved backend is configured.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .models import sha


@dataclass(frozen=True)
class QueryRewrite:
    """One candidate produced without access to papers or retrieval results."""

    query: str
    model: str
    prompt_version: str


QueryRewriter = Callable[[str], Awaitable[QueryRewrite]]


def _literals(text: str) -> list[str]:
    """Terms whose spelling is part of the user's condition, not prose to translate."""
    normalized = unicodedata.normalize("NFKC", text)
    values = re.findall(r"[A-Za-z][A-Za-z0-9_.+/#-]*|[<>≤≥]|\d+(?:\.\d+)?(?:\s*[%‰])?", normalized)
    return list(dict.fromkeys(values))


def _literal_key(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def validate_faithful_rewrite(original: str, rewritten: str) -> list[str]:
    """Return deterministic rejection reasons; this is not a semantic-equivalence proof."""
    candidate = unicodedata.normalize("NFKC", rewritten).strip()
    if not candidate:
        return ["empty_rewrite"]
    if len(candidate) > 4000:
        return ["rewrite_too_long"]

    candidate_folded = candidate.casefold()
    candidate_literals = {_literal_key(value) for value in _literals(candidate)}
    missing = [
        value for value in _literals(original) if _literal_key(value) not in candidate_literals
    ]
    reasons = ["protected_literal_missing:" + value for value in missing]

    # The check is deliberately narrow: it only catches a dropped explicit
    # negation. It never claims that a retained word proves semantic fidelity.
    original_has_negation = bool(re.search(r"没有|未|无|不|非|否", original))
    candidate_has_negation = bool(re.search(r"\b(?:no|not|without|none|never)\b", candidate_folded))
    if original_has_negation and not candidate_has_negation:
        reasons.append("explicit_negation_missing")
    return reasons


def audit(
    *,
    requested: str,
    original: str,
    rewrite: QueryRewrite | None = None,
    status: str,
    rejection_reasons: list[str] | None = None,
) -> dict:
    """Build response-safe provenance; callers retain the original query verbatim."""
    data = {
        "requested": requested,
        "status": status,
        "original_query": original,
        "original_query_hash": sha(original.encode()),
        "rewritten_query": rewrite.query if rewrite else None,
        "rewritten_query_hash": sha(rewrite.query.encode()) if rewrite else None,
        "model": rewrite.model if rewrite else None,
        "prompt_version": rewrite.prompt_version if rewrite else None,
        "validation": {
            "method": "protected-literals-and-explicit-negation-v1",
            "rejection_reasons": rejection_reasons or [],
            "semantic_equivalence_verified": False,
        },
    }
    return data
