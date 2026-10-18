"""Compliance constants shared by every outbound AI/ML call (dependency-free on purpose)."""

from __future__ import annotations

from collections.abc import Mapping

DATA_RETENTION_HEADER = "Data-Retention"
MANDATORY_HEADERS: Mapping[str, str] = {DATA_RETENTION_HEADER: "false"}
