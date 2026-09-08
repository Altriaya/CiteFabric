"""Generate or check the versioned public JSON Schema snapshots."""

import argparse
import json
from pathlib import Path

from citefabric.mcp_server import TOOLS
from citefabric.models import (
    Document,
    Edition,
    EvidenceObject,
    EvidenceReceipt,
    ExtractionSnapshot,
    MetadataSnapshot,
    Paper,
    Result,
)


def main(check=False):
    root = Path(__file__).resolve().parents[1] / "schemas" / "0.1"
    root.mkdir(parents=True, exist_ok=True)
    models = {name + ".input": model for name, (model, _) in TOOLS.items()}
    models.update(
        {
            model.__name__: model
            for model in [
                Result,
                Paper,
                Edition,
                MetadataSnapshot,
                Document,
                ExtractionSnapshot,
                EvidenceObject,
                EvidenceReceipt,
            ]
        }
    )
    for name, model in models.items():
        path = root / (name + ".schema.json")
        text = (
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                raise SystemExit(f"Schema snapshot differs: {path.name}")
        else:
            path.write_text(text, encoding="utf-8")
    print(f"{'Checked' if check else 'Generated'} {len(models)} public schemas.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    main(parser.parse_args().check)
