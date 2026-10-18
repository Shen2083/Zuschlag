"""Create `.env` for `make demo` from `.env.example` with fresh random secrets.

Each `change-me-*` placeholder gets its own random value, consistently wherever
it appears (a password and the URL that embeds it stay in sync). Never
overwrites an existing `.env`.
"""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / ".env"
DEMO_TENANT = "5e1d0c3a-7b1f-4c2e-9a55-0d3f6c8b2a10"

if TARGET.exists():
    sys.exit(f"{TARGET} exists; leaving it untouched")

text = (ROOT / ".env.example").read_text(encoding="utf-8")
values: dict[str, str] = {}


def secret(match: re.Match[str]) -> str:
    token = match.group(0)
    size = 32 if token.endswith("64-hex-chars") else 16
    return values.setdefault(token, secrets.token_hex(size))


text = re.sub(r"change-me-[A-Za-z0-9-]+", secret, text)
text = re.sub(r"^DEV_TENANT_ID=.*$", f"DEV_TENANT_ID={DEMO_TENANT}", text, flags=re.MULTILINE)
TARGET.write_text(text, encoding="utf-8")
TARGET.chmod(0o600)
print(f"wrote {TARGET} with random demo secrets")
