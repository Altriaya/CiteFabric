"""Create a clearly labeled development fixture from an authoring worksheet.

This bootstraps execution and replay testing only.  Its templated questions are
not a substitute for independently authored natural-language evaluation items.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

PAPERS = {
    "bert": (
        "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "nlp",
        "https://arxiv.org/abs/1810.04805",
        16,
    ),
    "gat": ("Graph Attention Networks", "graph_learning", "https://arxiv.org/abs/1710.10903", 12),
    "ddpm": (
        "Denoising Diffusion Probabilistic Models",
        "generative_vision",
        "https://arxiv.org/abs/2006.11239",
        25,
    ),
    "end2end-driving": (
        "End to End Learning for Self-Driving Cars",
        "autonomous_driving",
        "https://arxiv.org/abs/1604.07316",
        9,
    ),
    "gw170817": (
        "Multi-messenger Observations of a Binary Neutron Star Merger",
        "astrophysics",
        "https://arxiv.org/abs/1710.05833",
        59,
    ),
    "quantum-supremacy": (
        "Quantum supremacy supplementary information",
        "quantum_computing",
        "https://arxiv.org/abs/1910.11333",
        67,
    ),
    "nuts": (
        "The No-U-Turn Sampler",
        "statistical_computation",
        "https://www.jmlr.org/papers/v15/hoffman14a.html",
        30,
    ),
    "deepvariant": (
        "Creating a universal SNP and small indel variant caller with deep neural networks",
        "computational_genomics",
        "https://www.biorxiv.org/content/10.1101/092890v6",
        24,
    ),
}
STOP = {
    "the",
    "and",
    "that",
    "with",
    "from",
    "this",
    "were",
    "have",
    "their",
    "shown",
    "table",
    "results",
    "paper",
}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def terms(quote: str) -> str:
    values = [
        x
        for x in re.findall(r"[A-Za-z][A-Za-z0-9-]+|\d+(?:\.\d+)?", quote)
        if x.casefold() not in STOP
    ]
    return " ".join(list(dict.fromkeys(values))[:6]) or "reported experimental result"


def review():
    return {
        "author_id": "codex-ai-self-review",
        "reviewer_ids": [],
        "independence": "self_review",
        "saw_retrieval_outputs": False,
        "adjudication": "Templated span-anchored development fixture; no retrieval was run before authoring.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worksheet", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--status", choices=["draft", "frozen"], default="draft")
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("Output already exists")
    worksheet = read(args.worksheet)
    papers, intents, cases = [], [], []
    for source in worksheet["papers"]:
        paper_id = source["paper_id"]
        title, domain, url, pages = PAPERS[paper_id]
        papers.append(
            {
                "paper_id": paper_id,
                "family_id": "offline-v4-holdout-" + paper_id,
                "title": title,
                "domain": domain,
                "source_url": url,
                "filename": source["filename"],
                "sha256": source["source_sha256"],
                "pages": pages,
                "edition_label": "frozen local PDF",
                "metadata_basis": "Downloaded source URL and SHA-256 fixed before fixture authoring.",
                "layer": "stress",
                "challenges": ["narrative", "formula", "single_page_table"],
            }
        )
        for index, candidate in enumerate(source["candidates"], 1):
            intent_id = f"{paper_id}-{index:02d}"
            key_terms = terms(candidate["quote"])
            verdict = (
                "supported" if index <= 6 else "contradicted" if index <= 8 else "insufficient"
            )
            query = {
                "en": key_terms
                if verdict != "insufficient"
                else "UnreportedConfigurationZZZ " + key_terms,
                "zh": "论文中关于 " + key_terms + " 的结论是什么？"
                if verdict != "insufficient"
                else "论文是否报告了 UnreportedConfigurationZZZ " + key_terms + "？",
            }
            claim = {
                "en": "The paper reports the result described by " + key_terms + "."
                if verdict == "supported"
                else "The paper does not report the result described by " + key_terms + "."
                if verdict == "contradicted"
                else "The paper reports UnreportedConfigurationZZZ for " + key_terms + ".",
                "zh": "论文报告了与 " + key_terms + " 有关的结果。"
                if verdict == "supported"
                else "论文没有报告与 " + key_terms + " 有关的结果。"
                if verdict == "contradicted"
                else "论文报告了 UnreportedConfigurationZZZ 与 " + key_terms + " 有关的结果。",
            }
            intents.append(
                {
                    "intent_id": intent_id,
                    "parent_intent_id": None,
                    "paper_id": paper_id,
                    "query": query,
                    "claim": claim,
                    "equivalence_review": review(),
                }
            )
            span = {
                "span_id": "s1",
                "unit_index": candidate["unit_index"],
                "page": candidate["page"],
                "start": candidate["start"],
                "end": candidate["end"],
                "quote": candidate["quote"],
                "role": "counterevidence" if verdict == "contradicted" else "result",
            }
            cases.append(
                {
                    "intent_id": intent_id,
                    "paper_id": paper_id,
                    "source_sha256": source["source_sha256"],
                    "extraction_text_sha256": source["extraction_text_sha256"].removeprefix(
                        "sha256:"
                    ),
                    "reference_verdict": verdict,
                    "rationale": "Templated development item; exact snapshot span is the audit target.",
                    "tags": ["condition_counterexample"]
                    if verdict == "contradicted"
                    else ["unreported_configuration"]
                    if verdict == "insufficient"
                    else ["method_definition"],
                    "spans": [] if verdict == "insufficient" else [span],
                    "requirements": []
                    if verdict == "insufficient"
                    else [
                        {
                            "requirement_id": "r1",
                            "dimension": "other",
                            "description": "Exact anchor passage",
                            "span_ids": ["s1"],
                            "visual_requirements": [],
                            "relation": "explicit text",
                            "derivation": None,
                        }
                    ],
                    "sufficient_sets": [] if verdict == "insufficient" else [["r1"]],
                    "absence_review": {
                        "sections_reviewed": ["entire extracted snapshot"],
                        "terms_searched": ["UnreportedConfigurationZZZ"],
                        "missing_conditions": "Synthetic unreported configuration token",
                        "limitations": "Templated absence task; not a natural-language scientific absence review.",
                    }
                    if verdict == "insufficient"
                    else None,
                    "review": review(),
                }
            )
    queries = {
        "schema_version": "round4-0.1",
        "kind": "queries",
        "protocol_version": "0.1-draft",
        "cohort_id": "offline-v4-span-anchored-development",
        "split": "development",
        "status": args.status,
        "papers": papers,
        "intents": intents,
    }
    args.output_dir.mkdir(parents=True)
    qpath = args.output_dir / "queries.json"
    qpath.write_text(json.dumps(queries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gold = {
        "schema_version": "round4-0.1",
        "kind": "gold",
        "protocol_version": queries["protocol_version"],
        "cohort_id": queries["cohort_id"],
        "queries_sha256": digest(qpath),
        "cases": cases,
    }
    (args.output_dir / "gold.json").write_text(
        json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
