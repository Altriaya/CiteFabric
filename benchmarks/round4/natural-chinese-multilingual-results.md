# Natural-Chinese multilingual retrieval development experiment

Date: 2026-09-29. Decision: **multilingual reranking is promising for natural Chinese, but is not ready to replace v2**.

## Scope and validity

This experiment uses eight local PDF families: BERT, DDPM, DeepVariant, end-to-end driving, GAT, GW170817, NUTS, and the supplementary material associated with the quantum-supremacy paper. The fixture contains 64 independent intents, each with natural Chinese and paired English wording: 48 answerable intents and 16 intentionally unanswerable intents. The Chinese questions avoid copying English answer phrases except for names, acronyms, numbers, and units needed to state the request.

Questions and exact source spans were authored before retrieval. Fresh extraction snapshots replayed every answerable span exactly. Retrieval and reranking processes did not receive a gold path and did not open gold; the post-hoc audit opened gold only after the candidate files existed.

This remains an **opened, AI-self-reviewed development set**. The same reviewer selected the papers, authored the questions, and reviewed the spans. The 16 absence judgments have not been independently verified. The score below is exact-span candidate recall, not semantic evidence sufficiency, answer correctness, or a promotion result.

## Arms

- `lexical_v2_candidates`: the existing v2 FTS/query-plan ranking.
- `multilingual_e5_candidates`: local `intfloat/multilingual-e5-small` embeddings, 384 dimensions and a 512-token maximum sequence length.
- `lexical_dense_rrf_candidates`: reciprocal-rank fusion of the top 48 lexical and dense candidates.
- `multilingual_cross_encoder_candidates`: local `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` reranking of the lexical+dense union, evaluated on Chinese only.

The two models were fetched from Hugging Face through an ephemeral `sentence-transformers` environment and then ran locally. Product dependencies, MCP behavior, and the default retrieval policy were unchanged. Model revision hashes are not pinned, so these model names alone are not yet a release-grade reproducibility record.

The default-budget simulation follows the single-paper limits used by `find_evidence`: candidates are visited in rank order, with at most four selected passages and 6,000 raw passage characters. It scores selected seeds before context expansion.

## Default-budget exact-span recall

The denominator is 48 answerable intents per language. A result passes only when the selected candidates fully contain all exact spans in one frozen sufficient set.

| Arm | English | 中文 |
| --- | ---: | ---: |
| lexical v2 | **31/48 (64.6%)** | 12/48 (25.0%) |
| multilingual E5 | 26/48 (54.2%) | 12/48 (25.0%) |
| lexical+dense RRF | 28/48 (58.3%) | 19/48 (39.6%) |
| multilingual cross-encoder | not run | **25/48 (52.1%)** |

The cross-encoder gains 15 Chinese intents and loses 2 relative to v2, a net gain of 13. Its gains cover seven of the eight paper families rather than one narrow domain. Per-paper Chinese changes are BERT 3→4, DDPM 2→4, DeepVariant 1→3, end-to-end driving 0→2, GAT 1→3, GW170817 1→2, NUTS 3→3, and quantum supplementary material 1→4.

| Language route | Exact-span recall |
| --- | ---: |
| English v2 + 中文 v2 | 43/96 (44.8%) |
| English v2 + 中文 RRF | 50/96 (52.1%) |
| English v2 + 中文 cross-encoder | **56/96 (58.3%)** |

The best experimental route improves the opened development set by 13/96 items, or 13.5 percentage points, over v2. It is still wrong to describe 58.3% as production-quality evidence retrieval: 40/96 answerable variants remain uncovered within the delivery budget.

## Candidate-pool and ranking diagnosis

| Chinese arm | @1 | @3 | @6 | @12 | @48 |
| --- | ---: | ---: | ---: | ---: | ---: |
| lexical v2 | 6/48 | 11/48 | 15/48 | 21/48 | 26/48 |
| multilingual E5 | 3/48 | 9/48 | 16/48 | 24/48 | 41/48 |
| lexical+dense RRF | 10/48 | 19/48 | 20/48 | 28/48 | 41/48 |
| multilingual cross-encoder | **14/48** | **22/48** | **25/48** | **33/48** | **42/48** |

Dense retrieval raises Chinese candidate availability from 26/48 to 41/48 at rank 48, so the experiment confirms a real cross-language recall gap in v2. Simple RRF only moves part of that gain into the delivery window and also weakens English, so it is rejected as the next default. The cross-encoder ranks the union better, but 42/48 at rank 48 versus 25/48 in the default budget shows that final selection remains a large bottleneck.

English v2 remains stronger than both dense-only and RRF under the default budget. Language routing is therefore justified as an experiment design; replacing lexical retrieval globally is not supported.

## Insufficient-query exposure

On the 16 Chinese intents whose reference verdict is `insufficient`, v2 selects at least one passage for 9/16; E5, RRF, and the cross-encoder do so for 16/16. Candidate exposure is not a harmful-mismatch verdict, but it proves that empty lexical retrieval can no longer act as an accidental abstention mechanism once semantic retrieval is enabled.

AI self-review found materially confusable packages that a later answer model could misuse:

- the request for 512×512 ImageNet FID retrieves CIFAR-10 and 256×256 LSUN FID values;
- the request for a 48-layer BERT retrieves 12-layer and 24-layer BERT results;
- the request for a collision rate after one million autonomous miles retrieves a 100-mile simulation and a 10-mile zero-intervention drive;
- the request for carbon emissions retrieves power-consumption figures, but no emissions result.

These examples do not establish an aggregate harmful-mismatch rate because the absence labels and package judgments are not independent. They do establish the required safety mechanism: evidence selection must preserve dataset, model/configuration, metric, number, unit, comparison, and negation constraints, and it must return `insufficient` when the package does not support all of them.

## Runtime

The E5 run processed 128 bilingual query variants and their per-paper passage embeddings in 14.51 seconds after model construction. The cross-encoder reranked 64 Chinese candidate unions in 52.99 seconds after model construction, about 0.83 seconds per query. Model loading/download time and production concurrency were not measured, so these numbers are diagnostic rather than a latency commitment.

## Decision and next experiment

Keep v2 as the default. Do not promote simple RRF. Preserve the cross-encoder arm as an experiment candidate; its +13 net answerable gain is large and spans multiple domains, but its two regressions, 40 remaining misses, and full insufficient-query exposure prevent release.

The next implementation should remain behind an experimental flag and combine multilingual candidate generation with a bounded selector that explicitly scores critical-condition coverage. Its evaluation must report both answerable exact-span sufficiency and insufficient harmful mismatch. Freeze that design before running it on new papers; after the opened development set is exhausted, use independently authored and reviewed paper families for the blind pilot and reserve the larger 12–15 paper, 100–150 intent set for the promotion gate.

Machine-readable local artifacts:

- `output/validation/round4/offline-v4-holdout-20260921/natural-fixture/queries.json`
- `output/validation/round4/offline-v4-holdout-20260921/natural-fixture/gold.json`
- `output/validation/round4/offline-v4-holdout-20260921/natural-dense-run.json`
- `output/validation/round4/offline-v4-holdout-20260921/natural-dense-audit-v2.json`
- `output/validation/round4/offline-v4-holdout-20260921/natural-dense-budget-audit-v2.json`
- `output/validation/round4/offline-v4-holdout-20260921/natural-rerank-run.json`
- `output/validation/round4/offline-v4-holdout-20260921/natural-rerank-audit-v2.json`
- `output/validation/round4/offline-v4-holdout-20260921/natural-rerank-budget-audit-v2.json`
