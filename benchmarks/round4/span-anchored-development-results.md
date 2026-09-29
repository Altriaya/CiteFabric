# 80-intent span-anchored development experiment

Date: 2026-09-29. Decision: **reject `offline_structured_v4` and the English-v2/Chinese-v4 route as release candidates**.

## Scope and validity

Eight previously unused local PDF families supplied 80 independent intents: BERT, DDPM, DeepVariant, end-to-end driving, GAT, GW170817, NUTS, and the supplementary material associated with the quantum-supremacy paper. Each paper contributed six supported, two contradicted, and two insufficient templated items. Queries, claims, source hashes, extraction hashes, exact spans, and conditions were frozen before retrieval.

The run process did not open gold. Gold was opened only after all retrieval calls completed, and the fixture replayed exactly against newly prepared extraction snapshots.

This is a **templated self-review development fixture**, despite the local directory retaining `holdout` in its historical name. Chinese questions contain English anchor terms copied from their source spans. The result tests bounded retrieval, policy differences, exact-span containment, and replay integrity; it does not measure natural Chinese semantic retrieval, semantic claim verification, harmful mismatch on insufficient claims, independent review, or promotion eligibility.

## Execution integrity

- 80 intents × 2 languages × 3 policies × 4 executions (cold plus three warm) = 1,920 MCP calls.
- 1,920/1,920 calls returned `ok`.
- Evidence replay failures: 0. Budget violations: 0.
- All 480 `(intent, language, policy)` groups were identical across the three warm repetitions.
- One `structured_v3` group changed between its cold call and warm calls because the derived structure index was created lazily; the predeclared first warm result was scored.

## Exact-span coverage

The denominator contains 64 answerable intents per language. An item passes only when returned evidence fully contains every frozen span in at least one sufficient set. This mechanical measurement is not semantic ESR.

| Policy | English | 中文 | Combined |
| --- | ---: | ---: | ---: |
| v2 | 58/64 (90.6%) | 58/64 (90.6%) | **116/128 (90.6%)** |
| structured_v3 | 58/64 (90.6%) | 58/64 (90.6%) | **116/128 (90.6%)** |
| offline_structured_v4 | 54/64 (84.4%) | 54/64 (84.4%) | **108/128 (84.4%)** |
| English v2 + 中文 v4 | 58/64 (90.6%) | 54/64 (84.4%) | **112/128 (87.5%)** |

Relative to v2, v4 gained `gat-07` but lost `bert-01`, `gw170817-02`, `gw170817-03`, `quantum-supremacy-03`, and `quantum-supremacy-04` in each language: one gain, five losses, net −4/64. v3 made no coverage change.

| Paper | v2 | structured_v3 | v4 |
| --- | ---: | ---: | ---: |
| BERT | 8/8 | 8/8 | 7/8 |
| DDPM | 8/8 | 8/8 | 8/8 |
| DeepVariant | 7/8 | 7/8 | 7/8 |
| End-to-end driving | 7/8 | 7/8 | 7/8 |
| GAT | 4/8 | 4/8 | 5/8 |
| GW170817 | 8/8 | 8/8 | 6/8 |
| NUTS | 8/8 | 8/8 | 8/8 |
| Quantum supplementary material | 8/8 | 8/8 | 6/8 |

The English and Chinese paper tables are identical because both query variants expose the same source-derived English anchors. This is direct evidence that the fixture cannot answer the intended cross-language generalization question.

## Cost at the scored first warm execution

| Arm | Mean initial response bytes | Mean full audit bytes | Query p95 |
| --- | ---: | ---: | ---: |
| v2 | 26,031 | 37,429 | 62.98 ms |
| structured_v3 | 29,742 | 41,391 | 64.59 ms |
| offline_structured_v4 | 27,015 | 38,427 | 70.09 ms |
| English v2 + 中文 v4 | 26,472 | 37,877 | 70.09 ms |

The language route costs about 1.7% more initial-response bytes and 1.2% more full-audit bytes than v2, while its p95 is about 11.3% higher. It also loses four Chinese answerable spans, so the added cost has no quality justification on this fixture.

## Decision and next experiment

Keep v2 as the default. Keep v4 only as a diagnostic implementation; do not enable language routing. Do not tune v4 against these 80 opened items.

The next valid quality experiment needs independently authored natural Chinese questions that do not expose English answer anchors, paired English equivalents reviewed before retrieval, realistic supported/contradicted/insufficient claims, and independent evidence-package ratings. Until that set exists, further changes to local glossary weights or RRF are unsupported.

Machine-readable artifacts are local:

- `output/validation/round4/offline-v4-holdout-20260921/run/run.json`
- `output/validation/round4/offline-v4-holdout-20260921/exact-span-coverage.json`
- `output/validation/round4/offline-v4-holdout-20260921/policy-comparison.json`
