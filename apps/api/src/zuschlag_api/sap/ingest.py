"""Idempotent ingestion of SAP master-data IDocs into tenant tables.

Guarantees, per IDoc (one material / one customer):

* **Exactly-once per DOCNUM.** `sap_idoc_receipts` records every accepted
  `(sender, DOCNUM)`. A re-delivery with the same content is acknowledged as
  `duplicate` and not applied again; the same DOCNUM with *different* content
  is refused (`IdocConflictError`), since that means data corruption or a
  misconfigured partner profile.
* **Order-safe.** Each object remembers the DOCNUM it came from. An IDoc older
  than the stored one (SAP queues can deliver out of order) is reported as
  `stale` and skipped. The guard sits in the SQL `ON CONFLICT ... WHERE`, so
  it also holds between concurrent requests.
* **No-op on unchanged data.** Objects whose business content hash matches are
  not rewritten (only their DOCNUM watermark advances), and an embedding is
  recomputed only when the embedded text changes.

A whole payload is one transaction: it is applied completely or not at all.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar

from sqlalchemy import Table, bindparam, case, delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from zuschlag_api.audit.service import record_audit
from zuschlag_api.db.session import TENANT_KEY
from zuschlag_api.embeddings.base import Embedder
from zuschlag_api.models import Customer, CustomerSalesArea, Material, SapIdocReceipt
from zuschlag_api.sap.master_data import CustomerMaster, IdocControl, MaterialMaster

Outcome = Literal["created", "updated", "unchanged", "stale", "duplicate"]
BATCH_SIZE = 500

MATERIALS: Table = Material.__table__  # type: ignore[assignment]
CUSTOMERS: Table = Customer.__table__  # type: ignore[assignment]
SALES_AREAS: Table = CustomerSalesArea.__table__  # type: ignore[assignment]
RECEIPTS: Table = SapIdocReceipt.__table__  # type: ignore[assignment]


class IdocConflictError(RuntimeError):
    """A DOCNUM was already received with different content (or concurrently)."""

    def __init__(self, sender: str, docnum: str, reason: str) -> None:
        self.sender, self.docnum = sender, docnum
        super().__init__(f"IDoc {sender}/{docnum}: {reason}")


@dataclass(frozen=True, slots=True)
class DocumentResult:
    sender: str
    docnum: str
    object_key: str
    outcome: Outcome


@dataclass(slots=True)
class IngestResult:
    idoc_type: str
    documents: list[DocumentResult] = field(default_factory=list)
    embedded: int = 0

    @property
    def counts(self) -> dict[str, int]:
        c = Counter(d.outcome for d in self.documents)
        return {k: c.get(k, 0) for k in ("created", "updated", "unchanged", "stale", "duplicate")}


Obj = TypeVar("Obj", MaterialMaster, CustomerMaster)


@dataclass(frozen=True, slots=True)
class _Prior:
    source_system: str | None
    source_docnum: int | None
    content_sha256: str | None
    embedding_text_sha256: str | None = None
    has_embedding: bool = False


def _batches(rows: Sequence[Any], size: int = BATCH_SIZE) -> Iterable[Sequence[Any]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant_id = session.info.get(TENANT_KEY)
    if tenant_id is None:
        raise RuntimeError("SAP ingestion requires a tenant session")
    return tenant_id  # type: ignore[no-any-return]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def _screen_receipts(
    session: AsyncSession, objects: Sequence[Obj], result: IngestResult
) -> list[Obj]:
    """Drop IDocs already received; refuse DOCNUM reuse with different content."""
    keys = {(o.control.sndprn, o.control.docnum) for o in objects}
    known: dict[tuple[str, str], str] = {}
    for chunk in _batches(sorted(keys)):
        rows = await session.execute(
            select(RECEIPTS.c.sender, RECEIPTS.c.docnum, RECEIPTS.c.content_sha256).where(
                tuple_(RECEIPTS.c.sender, RECEIPTS.c.docnum).in_(list(chunk))
            )
        )
        known.update({(r.sender, r.docnum): r.content_sha256 for r in rows})

    fresh: list[Obj] = []
    for obj in objects:
        key = (obj.control.sndprn, obj.control.docnum)
        if key in known:
            if known[key] != obj.content_sha256:
                raise IdocConflictError(*key, "already received with different content")
            result.documents.append(DocumentResult(*key, _object_key(obj), "duplicate"))
            continue
        known[key] = obj.content_sha256  # also catches repeats inside one payload
        fresh.append(obj)
    return fresh


def _object_key(obj: MaterialMaster | CustomerMaster) -> str:
    return obj.matnr if isinstance(obj, MaterialMaster) else obj.kunnr


def _latest_per_key(objects: Sequence[Obj]) -> tuple[dict[str, Obj], list[Obj]]:
    """Newest IDoc per object key; older ones in the same payload are superseded."""
    latest: dict[str, Obj] = {}
    for obj in objects:
        key = _object_key(obj)
        current = latest.get(key)
        if current is None or obj.control.docnum_int > current.control.docnum_int:
            latest[key] = obj
    superseded = [o for o in objects if latest[_object_key(o)] is not o]
    return latest, superseded


def _classify(obj: MaterialMaster | CustomerMaster, prior: _Prior | None) -> Outcome:
    if prior is None:
        return "created"
    same_system = prior.source_system == obj.control.sndprn
    if (
        same_system
        and prior.source_docnum is not None
        and obj.control.docnum_int < prior.source_docnum
    ):
        return "stale"
    if prior.content_sha256 == obj.content_sha256:
        return "unchanged"
    return "updated"


def _newer_than_stored(table: Table) -> Any:
    """SQL guard: apply only if the incoming DOCNUM is not older than the stored one."""
    excluded = pg_insert(table).excluded
    return (
        table.c.source_docnum.is_(None)
        | table.c.source_system.is_distinct_from(excluded.source_system)
        | (table.c.source_docnum <= excluded.source_docnum)
    )


async def _advance_watermarks(
    session: AsyncSession,
    table: Table,
    key_col: str,
    objs: Sequence[MaterialMaster | CustomerMaster],
) -> None:
    """For unchanged objects, record the newer DOCNUM without touching content."""
    if not objs:
        return
    stmt = (
        update(table)
        .where(
            table.c.tenant_id == _tenant(session),
            table.c[key_col] == bindparam("key"),
            table.c.source_docnum.is_(None) | (table.c.source_docnum < bindparam("docnum")),
        )
        .values(
            source_system=bindparam("system"),
            source_docnum=bindparam("docnum"),
            updated_at=table.c.updated_at,  # provenance only: not a content change
        )
    )
    params = [
        {"key": _object_key(o), "docnum": o.control.docnum_int, "system": o.control.sndprn}
        for o in objs
    ]
    for chunk in _batches(params):
        await session.execute(stmt, list(chunk))


async def _record_receipts(
    session: AsyncSession, idoc_type: str, message_type: str, docs: Sequence[tuple[Obj, Outcome]]
) -> None:
    if not docs:
        return
    tenant_id = _tenant(session)
    rows = [
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "sender": o.control.sndprn,
            "docnum": o.control.docnum,
            "idoc_type": idoc_type,
            "message_type": message_type,
            "object_key": _object_key(o),
            "content_sha256": o.content_sha256,
            "outcome": outcome,
            "object_count": 1,
        }
        for o, outcome in docs
    ]
    stmt = (
        pg_insert(RECEIPTS)
        .on_conflict_do_nothing(index_elements=["tenant_id", "sender", "docnum"])
        .returning(RECEIPTS.c.docnum)
    )
    claimed = 0
    for chunk in _batches(rows):
        claimed += len((await session.execute(stmt, list(chunk))).all())
    if claimed != len(rows):
        # Another request committed one of these DOCNUMs while we were working.
        first = docs[0][0].control
        raise IdocConflictError(first.sndprn, first.docnum, "delivered concurrently; retry")


async def _audit(
    session: AsyncSession,
    result: IngestResult,
    controls: Sequence[IdocControl],
    *,
    actor_id: str,
    ip_sha256: str | None,
    payload_sha256: str,
) -> None:
    docnums = sorted(c.docnum for c in controls)
    await record_audit(
        session,
        actor_id=actor_id,
        action=f"sap.{result.idoc_type.lower()}.ingested",
        entity_type="sap_idoc_payload",
        entity_id=payload_sha256,
        ip_sha256=ip_sha256,
        context={
            "idoc_type": result.idoc_type,
            "senders": sorted({c.sndprn for c in controls}),
            "docnum_first": docnums[0] if docnums else None,
            "docnum_last": docnums[-1] if docnums else None,
            "idocs": len(controls),
            "embedded": result.embedded,
            **result.counts,
        },
    )


async def _ingest(
    session: AsyncSession,
    objects: Sequence[Obj],
    *,
    idoc_type: str,
    message_type: str,
    table: Table,
    key_col: str,
    prefetch: Callable[[AsyncSession, list[str]], Awaitable[dict[str, _Prior]]],
    apply: Callable[[AsyncSession, list[tuple[Obj, _Prior | None]]], Awaitable[set[str]]],
    result: IngestResult,
) -> list[tuple[Obj, Outcome]]:
    fresh = await _screen_receipts(session, objects, result)
    latest, superseded = _latest_per_key(fresh)
    priors = await prefetch(session, list(latest))

    decided: list[tuple[Obj, Outcome]] = [(o, "stale") for o in superseded]
    to_write: list[tuple[Obj, _Prior | None]] = []
    unchanged: list[Obj] = []
    for key, obj in latest.items():
        outcome = _classify(obj, priors.get(key))
        if outcome in ("created", "updated"):
            to_write.append((obj, priors.get(key)))
        elif outcome == "unchanged":
            unchanged.append(obj)
            decided.append((obj, outcome))
        else:
            decided.append((obj, outcome))

    applied = await apply(session, to_write)
    for obj, prior in to_write:
        # Rows the SQL guard refused lost a race against a newer DOCNUM.
        written: Outcome = "created" if prior is None else "updated"
        decided.append((obj, written if _object_key(obj) in applied else "stale"))
    await _advance_watermarks(session, table, key_col, unchanged)

    await _record_receipts(session, idoc_type, message_type, decided)
    order = {id(o): i for i, o in enumerate(objects)}
    for obj, outcome in sorted(decided, key=lambda d: order[id(d[0])]):
        result.documents.append(
            DocumentResult(obj.control.sndprn, obj.control.docnum, _object_key(obj), outcome)
        )
    return decided


# --------------------------------------------------------------------------- #
# Materials (MATMAS05)
# --------------------------------------------------------------------------- #


async def _prefetch_materials(session: AsyncSession, keys: list[str]) -> dict[str, _Prior]:
    priors: dict[str, _Prior] = {}
    for chunk in _batches(keys):
        rows = await session.execute(
            select(
                MATERIALS.c.matnr,
                MATERIALS.c.source_system,
                MATERIALS.c.source_docnum,
                MATERIALS.c.content_sha256,
                MATERIALS.c.embedding_text_sha256,
                MATERIALS.c.embedding.is_not(None).label("has_embedding"),
            ).where(MATERIALS.c.tenant_id == _tenant(session), MATERIALS.c.matnr.in_(chunk))
        )
        for r in rows:
            priors[r.matnr] = _Prior(
                r.source_system,
                r.source_docnum,
                r.content_sha256,
                r.embedding_text_sha256,
                r.has_embedding,
            )
    return priors


async def ingest_materials(
    session: AsyncSession,
    materials: Sequence[MaterialMaster],
    *,
    embedder: Embedder | None,
    preferred_languages: Sequence[str],
    actor_id: str,
    ip_sha256: str | None,
    payload_sha256: str,
) -> IngestResult:
    result = IngestResult("MATMAS05")
    tenant_id = _tenant(session)

    async def apply(
        session: AsyncSession, items: list[tuple[MaterialMaster, _Prior | None]]
    ) -> set[str]:
        if not items:
            return set()
        texts = {m.matnr: m.embedding_text(preferred_languages) for m, _ in items}
        text_hash = {k: _sha256(v) for k, v in texts.items()}
        needs = [
            m.matnr
            for m, prior in items
            if prior is None
            or not prior.has_embedding
            or prior.embedding_text_sha256 != text_hash[m.matnr]
        ]
        vectors: dict[str, list[float]] = {}
        if embedder is not None and needs:
            for chunk in _batches(needs, 256):
                embedded = await embedder.embed_documents([texts[k] for k in chunk])
                vectors.update(zip(chunk, embedded, strict=True))
        result.embedded += len(vectors)
        now = datetime.now(UTC)

        rows = [
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "matnr": m.matnr,
                "material_type": m.mtart,
                "material_group": m.matkl,
                "base_uom": m.meins,
                "gross_weight": m.brgew,
                "net_weight": m.ntgew,
                "weight_unit": m.gewei,
                "description": m.description(preferred_languages),
                "descriptions": m.descriptions_by_language,
                "is_active": not m.is_deleted,
                "source_system": m.control.sndprn,
                "source_docnum": m.control.docnum_int,
                "content_sha256": m.content_sha256,
                "embedding": vectors.get(m.matnr),
                "embedding_model": embedder.model_name if m.matnr in vectors and embedder else None,
                "embedding_text_sha256": text_hash[m.matnr],
                "embedded_at": now if m.matnr in vectors else None,
            }
            for m, _ in items
        ]
        ins = pg_insert(MATERIALS)
        ex = ins.excluded
        # Keep the stored vector when the text is unchanged and none was computed;
        # drop it when the text changed but no embedder is configured.
        keep_old = (ex.embedding.is_(None)) & (
            MATERIALS.c.embedding_text_sha256 == ex.embedding_text_sha256
        )
        stmt = ins.on_conflict_do_update(
            index_elements=["tenant_id", "matnr"],
            set_={
                **{
                    c: ex[c]
                    for c in (
                        "material_type",
                        "material_group",
                        "base_uom",
                        "gross_weight",
                        "net_weight",
                        "weight_unit",
                        "description",
                        "descriptions",
                        "is_active",
                        "source_system",
                        "source_docnum",
                        "content_sha256",
                        "embedding_text_sha256",
                    )
                },
                "embedding": case((keep_old, MATERIALS.c.embedding), else_=ex.embedding),
                "embedding_model": case(
                    (keep_old, MATERIALS.c.embedding_model), else_=ex.embedding_model
                ),
                "embedded_at": case((keep_old, MATERIALS.c.embedded_at), else_=ex.embedded_at),
                "updated_at": func.now(),
            },
            where=_newer_than_stored(MATERIALS),
        ).returning(MATERIALS.c.matnr)
        applied: set[str] = set()
        for chunk in _batches(rows):
            applied.update((await session.execute(stmt, list(chunk))).scalars())
        return applied

    decided = await _ingest(
        session,
        materials,
        idoc_type="MATMAS05",
        message_type="MATMAS",
        table=MATERIALS,
        key_col="matnr",
        prefetch=_prefetch_materials,
        apply=apply,
        result=result,
    )
    await _audit(
        session,
        result,
        [m.control for m, _ in decided],
        actor_id=actor_id,
        ip_sha256=ip_sha256,
        payload_sha256=payload_sha256,
    )
    return result


# --------------------------------------------------------------------------- #
# Customers (DEBMAS06)
# --------------------------------------------------------------------------- #


async def _prefetch_customers(session: AsyncSession, keys: list[str]) -> dict[str, _Prior]:
    priors: dict[str, _Prior] = {}
    for chunk in _batches(keys):
        rows = await session.execute(
            select(
                CUSTOMERS.c.kunnr,
                CUSTOMERS.c.source_system,
                CUSTOMERS.c.source_docnum,
                CUSTOMERS.c.content_sha256,
            ).where(CUSTOMERS.c.tenant_id == _tenant(session), CUSTOMERS.c.kunnr.in_(chunk))
        )
        for r in rows:
            priors[r.kunnr] = _Prior(r.source_system, r.source_docnum, r.content_sha256)
    return priors


async def ingest_customers(
    session: AsyncSession,
    customers: Sequence[CustomerMaster],
    *,
    actor_id: str,
    ip_sha256: str | None,
    payload_sha256: str,
) -> IngestResult:
    result = IngestResult("DEBMAS06")
    tenant_id = _tenant(session)

    async def apply(
        session: AsyncSession, items: list[tuple[CustomerMaster, _Prior | None]]
    ) -> set[str]:
        if not items:
            return set()
        rows = [
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "kunnr": c.kunnr,
                "name1": c.name1,
                "name2": c.name2,
                "street": c.stras,
                "city": c.ort01,
                "postal_code": c.pstlz,
                "country": c.land1,
                "region": c.regio,
                "language": c.language,
                "is_active": not c.is_deleted,
                "source_system": c.control.sndprn,
                "source_docnum": c.control.docnum_int,
                "content_sha256": c.content_sha256,
            }
            for c, _ in items
        ]
        ins = pg_insert(CUSTOMERS)
        content_cols = [k for k in rows[0] if k not in ("id", "tenant_id", "kunnr")]
        stmt = ins.on_conflict_do_update(
            index_elements=["tenant_id", "kunnr"],
            set_={**{c: ins.excluded[c] for c in content_cols}, "updated_at": func.now()},
            where=_newer_than_stored(CUSTOMERS),
        ).returning(CUSTOMERS.c.id, CUSTOMERS.c.kunnr)
        applied: dict[str, uuid.UUID] = {}
        for chunk in _batches(rows):
            applied.update({r.kunnr: r.id for r in await session.execute(stmt, list(chunk))})

        # Sales areas of every applied customer are replaced by the IDoc's snapshot.
        if applied:
            for chunk in _batches(list(applied.values())):
                await session.execute(
                    delete(SALES_AREAS).where(
                        SALES_AREAS.c.tenant_id == tenant_id, SALES_AREAS.c.customer_id.in_(chunk)
                    )
                )
            areas = [
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "customer_id": applied[c.kunnr],
                    "sales_org": a.vkorg,
                    "distribution_channel": a.vtweg,
                    "division": a.spart,
                    "currency": a.waers,
                    "payment_terms": a.zterm,
                    "is_active": not a.loevm,
                }
                for c, _ in items
                if c.kunnr in applied
                for a in c.sales_areas
            ]
            for chunk in _batches(areas):
                await session.execute(pg_insert(SALES_AREAS), list(chunk))
        return set(applied)

    decided = await _ingest(
        session,
        customers,
        idoc_type="DEBMAS06",
        message_type="DEBMAS",
        table=CUSTOMERS,
        key_col="kunnr",
        prefetch=_prefetch_customers,
        apply=apply,
        result=result,
    )
    await _audit(
        session,
        result,
        [c.control for c, _ in decided],
        actor_id=actor_id,
        ip_sha256=ip_sha256,
        payload_sha256=payload_sha256,
    )
    return result
