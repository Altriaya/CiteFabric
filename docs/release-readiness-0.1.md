# CiteFabric 0.1 release readiness

Date: 2026-09-29. Evaluated commit: `61954abfbdecb617506ede08504916d7cdd8415c`.

Decision: **the source repository passes the 0.1 release-candidate gate**. The release claim is bounded to paper discovery, version-aware identity, exact evidence retrieval, replayable grounding receipts, and citation provenance. Semantic claim verification remains explicitly unavailable until a verifier is configured in a later release.

## Golden path

The live workflow used `arxiv:1810.04805v2` and the query `SQuAD v1.1 Test F1 93.2`:

1. arXiv search returned five papers and matched the intended BERT edition.
2. The selected paper and edition resolved with verified identity.
3. CiteFabric downloaded the PDF from arXiv and parsed 16/16 physical pages.
4. `find_evidence` returned three passages within 5,430 characters. The leading passage was page 7 and contained `93.2`.
5. `verify_claim` produced a receipt with `grounding_status=verified` and correctly abstained with `verdict=unavailable` / `verifier_not_configured`.
6. The receipt resource replayed exactly.
7. BibTeX export succeeded and its provenance manifest referenced the receipt with verified grounding.

The public-network run passed in [GitHub Actions](https://github.com/Altriaya/CiteFabric/actions/runs/36526516242). It is a release smoke check, not an availability SLA or semantic-accuracy evaluation. The reusable runner is `scripts/online_release_smoke.py`; the workflow remains manual to avoid treating upstream availability as a deterministic CI requirement.

## Local installation and MCP path

- `uv build` produced both `citefabric-0.1.0.tar.gz` and `citefabric-0.1.0-py3-none-any.whl`.
- The wheel installed into a fresh Python 3.13 virtual environment outside the repository; the installed `citefabric doctor --json` returned `ok` with SQLite FTS5 enabled.
- A real stdio MCP subprocess exposed exactly five tools with output schemas.
- `get_paper`, `find_evidence`, evidence-resource replay, receipt-resource replay, BibTeX export, and CSL-JSON export all passed against the fresh BERT workspace.
- The reusable local runner is `scripts/release_smoke.py`.

The local host maps public domains into `198.18.0.0/15`; automatic PDF download was therefore rejected with `permission_denied` by the intended SSRF protection. Explicit local PDF import succeeded with verified arXiv identifier/title binding. The GitHub-hosted public-network run independently demonstrated automatic arXiv download, so this local network property is not an unresolved product failure.

## Automated checks

The normal [CI run](https://github.com/Altriaya/CiteFabric/actions/runs/36526507771) passed all six combinations of Linux, macOS, and Windows with Python 3.11 and 3.13. Every job ran:

- locked dependency synchronization;
- Ruff lint and format checks;
- mypy over `src`;
- 129 pytest tests;
- public JSON Schema snapshot verification;
- wheel and source-distribution builds.

The Node.js runtime deprecation emitted by `actions/checkout@v4` is an upstream workflow warning and did not affect any check. It should be removed by upgrading the checkout action when its Node 24 release is adopted.

## Remaining scope after 0.1

- PyPI and MCP Registry publication are separate distribution steps.
- `verify_claim` does not yet produce semantic support, contradiction, or insufficiency verdicts.
- OCR, reliable table-cell semantics, Zotero/PMC adapters, APA/IEEE rendering, and production service operation remain outside 0.1.
- Multilingual E5 and cross-encoder work remains development research; v2 remains the default retrieval policy.
