"""Each entry point must import on its own in a fresh interpreter (no import cycles)."""

from __future__ import annotations

import subprocess
import sys

import pytest

ENTRY_POINTS = [
    "zuschlag_api.main",
    "zuschlag_api.models",
    "zuschlag_api.embeddings",
    "zuschlag_api.llm.client",
    "zuschlag_api.sap.ingest",
    "zuschlag_api.api.routes.sap",
    "zuschlag_api.audit.service",
    "zuschlag_api.rfq.pipeline",
    "zuschlag_api.api.routes.quotes",
    "zuschlag_api.core.config",
]


@pytest.mark.parametrize("module", ENTRY_POINTS)
def test_module_imports_in_isolation(module: str) -> None:
    proc = subprocess.run(  # noqa: S603 — fixed interpreter and module list
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=60,
        env={"EMBEDDING_PROVIDER": "hashing", "PATH": ""},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
