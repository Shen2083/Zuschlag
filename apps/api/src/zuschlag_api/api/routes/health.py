from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text

from zuschlag_api.core.config import Settings, get_settings
from zuschlag_api.db.session import get_engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    """Liveness plus the (non-secret) residency/retention posture."""
    return {
        "status": "ok",
        "environment": settings.environment.value,
        "cloud_provider": settings.cloud_provider.value,
        "region": settings.cloud_region,
        "llm": {
            "provider": settings.llm_provider,
            "zdr_attested": settings.llm_provider != "disabled" and settings.llm_zdr_attested,
        },
    }


@router.get("/readyz")
async def readyz() -> dict[str, str]:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc
    return {"status": "ready"}
