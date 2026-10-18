"""SAP master-data inbound endpoints (target of an SAP "XML HTTP" port, SM59 type G).

Each endpoint accepts either the raw IDoc XML (`application/xml`, `text/xml`)
or `multipart/form-data` with one or more XML files. Responses are always 2xx
for accepted payloads, including pure re-deliveries, so SAP does not retry.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from starlette.datastructures import UploadFile

from zuschlag_api.api.deps import PrincipalDep, TenantDb
from zuschlag_api.core.config import Settings, get_settings
from zuschlag_api.embeddings import Embedder, EmbeddingError, embedder_from_settings
from zuschlag_api.sap.idoc_xml import IdocParseError
from zuschlag_api.sap.ingest import (
    IdocConflictError,
    IngestResult,
    ingest_customers,
    ingest_materials,
)
from zuschlag_api.sap.master_data import IdocValidationError, parse_debmas06, parse_matmas05

router = APIRouter(prefix="/api/v1/sap", tags=["sap"])

XML_TYPES = {"application/xml", "text/xml"}
_OPENAPI_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "application/xml": {"schema": {"type": "string"}},
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "array", "items": {"type": "string", "format": "binary"}}
                    },
                }
            },
        },
    }
}


@lru_cache
def get_embedder() -> Embedder | None:
    """Process-wide embedder (the model is loaded once and reused)."""
    return embedder_from_settings(get_settings())


class DocumentOut(BaseModel):
    sender: str
    docnum: str
    object_key: str
    outcome: Literal["created", "updated", "unchanged", "stale", "duplicate"]


class IngestOut(BaseModel):
    idoc_type: str
    idocs: int
    created: int
    updated: int
    unchanged: int
    stale: int
    duplicate: int
    embedded: int
    documents: list[DocumentOut]

    @classmethod
    def from_result(cls, result: IngestResult) -> IngestOut:
        return cls(
            idoc_type=result.idoc_type,
            idocs=len(result.documents),
            embedded=result.embedded,
            documents=[
                DocumentOut.model_validate(d, from_attributes=True) for d in result.documents
            ],
            **result.counts,
        )


async def _read_limited(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"payload exceeds {limit} bytes")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"payload exceeds {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def read_idoc_payloads(request: Request, settings: Settings) -> list[bytes]:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    limit = settings.sap_idoc_max_bytes
    if content_type in XML_TYPES:
        body = await _read_limited(request, limit)
        if not body.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty body")
        return [body]
    if content_type == "multipart/form-data":
        declared = request.headers.get("content-length")
        total_limit = limit * settings.sap_idoc_max_files
        if declared and declared.isdigit() and int(declared) > total_limit:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "upload too large")
        payloads: list[bytes] = []
        async with request.form(max_files=settings.sap_idoc_max_files, max_fields=10) as form:
            files = [v for _, v in form.multi_items() if isinstance(v, UploadFile)]
            if not files:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "no file part in multipart body")
            for upload in files:
                data = await upload.read(limit + 1)
                if len(data) > limit:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        f"{upload.filename} exceeds {limit} bytes",
                    )
                payloads.append(data)
        return payloads
    raise HTTPException(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "send application/xml, text/xml or multipart/form-data",
    )


def _parse_all(payloads: list[bytes], parser: Any) -> list[Any]:
    objects: list[Any] = []
    try:
        for payload in payloads:
            objects.extend(parser(payload))
    except IdocParseError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except IdocValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            [
                {"idoc_index": i.idoc_index, "docnum": i.docnum, "errors": i.errors}
                for i in exc.issues
            ],
        ) from exc
    return objects


def _digest(payloads: list[bytes]) -> str:
    h = hashlib.sha256()
    for p in payloads:
        h.update(hashlib.sha256(p).digest())
    return h.hexdigest()


@router.post("/matmas", openapi_extra=_OPENAPI_BODY)
async def ingest_matmas(
    request: Request,
    principal: PrincipalDep,
    db: TenantDb,
    settings: Annotated[Settings, Depends(get_settings)],
    embedder: Annotated[Embedder | None, Depends(get_embedder)],
) -> IngestOut:
    """Ingest MATMAS05 material-master IDocs (create/update, idempotent)."""
    payloads = await read_idoc_payloads(request, settings)
    materials = _parse_all(payloads, parse_matmas05)
    try:
        result = await ingest_materials(
            db,
            materials,
            embedder=embedder,
            preferred_languages=settings.sap_description_languages,
            actor_id=principal.actor_id,
            ip_sha256=principal.ip_sha256,
            payload_sha256=_digest(payloads),
        )
    except IdocConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except EmbeddingError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "embedding backend unavailable"
        ) from exc
    return IngestOut.from_result(result)


@router.post("/debmas", openapi_extra=_OPENAPI_BODY)
async def ingest_debmas(
    request: Request,
    principal: PrincipalDep,
    db: TenantDb,
    settings: Annotated[Settings, Depends(get_settings)],
) -> IngestOut:
    """Ingest DEBMAS06 customer-master IDocs (create/update, idempotent)."""
    payloads = await read_idoc_payloads(request, settings)
    customers = _parse_all(payloads, parse_debmas06)
    try:
        result = await ingest_customers(
            db,
            customers,
            actor_id=principal.actor_id,
            ip_sha256=principal.ip_sha256,
            payload_sha256=_digest(payloads),
        )
    except IdocConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return IngestOut.from_result(result)
