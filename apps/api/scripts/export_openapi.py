"""Write the API's OpenAPI document, the source of the web app's TypeScript types.

uv run python scripts/export_openapi.py          # -> packages/api-types/generated/openapi.json
uv run python scripts/export_openapi.py --check  # CI: fail if the committed file is stale
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Hermetic settings: the schema must not depend on the local environment or extras.
os.environ.update(
    {"ENVIRONMENT": "development", "EMBEDDING_PROVIDER": "disabled", "LLM_PROVIDER": "disabled"}
)

from zuschlag_api.main import create_app

TARGET = (
    Path(__file__).resolve().parents[3] / "packages" / "api-types" / "generated" / "openapi.json"
)


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    document = render()
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != document:
            print(f"{TARGET} is stale: run `uv run python scripts/export_openapi.py`")
            return 1
        print("openapi.json is up to date")
        return 0
    TARGET.write_text(document, encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
