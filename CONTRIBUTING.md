# Contributing

Use Python 3.11+ and `uv sync --locked`. Run:

```bash
uv run pytest -q
uv run ruff check src tests examples scripts
uv run ruff format --check src tests examples scripts
uv run mypy src
uv run python scripts/export_schemas.py --check
```

Tests must work without network access or API keys. Add small synthetic or redistributable fixtures for provider quirks, identity conflicts, document versions and evidence locators. Never commit credentials, private documents or personal library metadata.

Keep source-specific behavior inside discovery adapters. Core services must return explicit partial failures and retain provenance. Do not turn missing evidence into a contradiction or use retrieval scores as semantic confidence.

When changing a public model, review compatibility and regenerate snapshots with `uv run python scripts/export_schemas.py`. Update the relevant design/implementation notes and add a behavioral regression test. Large parser/ML integrations should be optional; they must not change the default installation cost.

Discuss proposed plugin interfaces before relying on them as stable APIs. The project is at 0.1 and adapters/internal storage APIs may still change.
