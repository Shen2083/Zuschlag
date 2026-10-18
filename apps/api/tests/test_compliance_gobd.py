"""GoBD compliance checks: approved quotes are frozen, changes create revisions.

The freeze is enforced by PostgreSQL triggers (migration 0005), so these tests
attack it both through the API and with raw SQL as the runtime role.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.test_integration_quote_studio import Q, Studio, by_position, studio  # noqa: F401
from tests.test_integration_rfq_pipeline import h  # noqa: F401 — fixture
from zuschlag_api.db.session import tenant_session
from zuschlag_api.models import Quote, QuoteAuditTrail
from zuschlag_api.quoting.service import snapshot_sha256

pytestmark = pytest.mark.integration
Sm = async_sessionmaker[AsyncSession]


def events(quote: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [e["details"] for e in quote["trail"] if e["event"] == name]


async def approved_v1(studio: Studio) -> dict[str, Any]:  # noqa: F811
    q = await studio.quote("catalog_de", customer_id="100077")
    await studio.patch(q, by_position(q, 20), matnr="RM-1430-SH20")
    await studio.calculate(q, "20")
    res = await studio.post(f"{Q}/{q['id']}/approve")
    assert res.status_code == 200, res.text
    data: dict[str, Any] = res.json()
    assert (data["status"], data["revision"]) == ("approved", 1)
    return data


async def _sql(sm: Sm, tenant: uuid.UUID, statement: str, **params: Any) -> None:
    async with tenant_session(tenant, sessionmaker=sm) as s:
        await s.execute(text(statement), params)


FROZEN_WRITES = {
    "change a price": "UPDATE quote_items SET unit_price = 1 WHERE quote_id = :q",
    "change a quantity": "UPDATE quote_items SET quantity = 1 WHERE quote_id = :q",
    "delete a line": "DELETE FROM quote_items WHERE quote_id = :q",
    "add a line": (
        "INSERT INTO quote_items (tenant_id, quote_id, position, kind, description, quantity,"
        " uom, match_status, sourcing) SELECT tenant_id, id, 990, 'service', 'Rabatt', 1,"
        " 'PCE', 'NOT_APPLICABLE', 'internal' FROM quotes WHERE id = :q"
    ),
    "change the net total": "UPDATE quotes SET net_total = 1 WHERE id = :q",
    "change the Zuschlag": "UPDATE quotes SET margin_pct = 99 WHERE id = :q",
    "reopen without a revision": "UPDATE quotes SET status = 'draft' WHERE id = :q",
    "skip a revision": "UPDATE quotes SET status = 'draft', revision = revision + 2 WHERE id = :q",
    "delete the quote": "DELETE FROM quotes WHERE id = :q",
}


@pytest.mark.parametrize("attempt", list(FROZEN_WRITES), ids=list(FROZEN_WRITES))
async def test_approved_quote_is_frozen_in_the_database(
    studio: Studio,  # noqa: F811
    sessionmaker: Sm,
    attempt: str,
) -> None:
    q = await approved_v1(studio)
    with pytest.raises(DBAPIError, match=r"GoBD|requires revision|frozen"):
        await _sql(sessionmaker, studio.h.tenant, FROZEN_WRITES[attempt], q=q["id"])
    after = (await studio.get(f"{Q}/{q['id']}")).json()
    assert (after["net_total"], after["status"], after["revision"]) == (
        q["net_total"],
        "approved",
        1,
    )


async def test_price_adjustment_creates_revision_v2_preserving_v1(studio: Studio) -> None:  # noqa: F811
    v1 = await approved_v1(studio)
    [approval] = events(v1, "quote.approved")
    assert approval["revision"] == "v1"
    assert approval["snapshot_sha256"] == snapshot_sha256(approval["snapshot"])

    castors = by_position(v1, 10)
    res = await studio.patch(v1, castors, unit_cost="41.20")
    assert res.status_code == 200, res.text
    v2 = res.json()
    assert (v2["status"], v2["revision"]) == ("draft", 2)
    assert v2["net_total"] != v1["net_total"]

    [revision] = events(v2, "quote.revision.created")
    assert (revision["revision"], revision["supersedes"], revision["reason"]) == (
        "v2",
        "v1",
        "item.edited",
    )
    # v1 is preserved exactly as approved: same content, same hash.
    assert revision["frozen_snapshot"] == approval["snapshot"]
    assert revision["frozen_snapshot_sha256"] == approval["snapshot_sha256"]
    frozen_castors = next(i for i in revision["frozen_snapshot"]["items"] if i["position"] == 10)
    assert Decimal(frozen_castors["unit_cost"]) == Decimal("38.90")
    assert revision["frozen_snapshot"]["net_total"] == v1["net_total"]
    [edit] = events(v2, "item.edited")[-1:]
    assert edit["revision"] == "v2"

    # v2 is approved in turn; the next adjustment (a Zuschlag change) opens v3.
    await studio.calculate(v2, "20")
    v2_approved = (await studio.post(f"{Q}/{v2['id']}/approve")).json()
    assert [a["revision"] for a in events(v2_approved, "quote.approved")] == ["v1", "v2"]
    await studio.calculate(v2, "25")
    v3 = (await studio.get(f"{Q}/{v2['id']}")).json()
    assert (v3["status"], v3["revision"]) == ("draft", 3)
    revisions = events(v3, "quote.revision.created")
    assert [(r["supersedes"], r["revision"], r["reason"]) for r in revisions] == [
        ("v1", "v2", "item.edited"),
        ("v2", "v3", "quote.calculated"),
    ]
    assert (
        revisions[1]["frozen_snapshot_sha256"]
        == events(v2_approved, "quote.approved")[1]["snapshot_sha256"]
    )


async def test_recalculating_an_approved_quote_unchanged_keeps_it_frozen(
    studio: Studio,  # noqa: F811
) -> None:
    v1 = await approved_v1(studio)
    await studio.calculate(v1, "20")  # same Zuschlag, VAT and terms
    after = (await studio.get(f"{Q}/{v1['id']}")).json()
    assert (after["status"], after["revision"]) == ("approved", 1)
    assert not events(after, "quote.revision.created")


async def test_synced_quote_is_final(studio: Studio, sessionmaker: Sm, tmp_path: Path) -> None:  # noqa: F811
    q = await approved_v1(studio)
    await studio.configure_sap(tmp_path)
    p = (await studio.post(f"{Q}/{q['id']}/sap-idoc/prepare")).json()
    sent = await studio.post(
        f"{Q}/{q['id']}/sap-idoc/send", {"docnum": p["docnum"], "sha256": p["sha256"]}
    )
    assert sent.status_code == 200, sent.text

    assert (await studio.patch(q, by_position(q, 10), unit_cost="1")).status_code == 409
    assert (await studio.post(f"{Q}/{q['id']}/calculate", {"zuschlag_pct": "5"})).status_code == 409
    for statement in (
        "UPDATE quotes SET status = 'draft', revision = revision + 1 WHERE id = :q",
        "UPDATE quotes SET last_idoc_docnum = '0000000000000001' WHERE id = :q",
        "UPDATE quote_items SET unit_price = 1 WHERE quote_id = :q",
    ):
        with pytest.raises(DBAPIError, match=r"synced|frozen"):
            await _sql(sessionmaker, studio.h.tenant, statement, q=q["id"])
    # Downloading the XML again does not overwrite the IDoc the quote was sent with.
    again = await studio.post(f"{Q}/{q['id']}/export-sap-idoc")
    assert again.status_code == 200
    final = (await studio.get(f"{Q}/{q['id']}")).json()
    assert final["last_idoc_docnum"] == p["docnum"]


async def test_revision_trail_cannot_be_rewritten(studio: Studio, sessionmaker: Sm) -> None:  # noqa: F811
    v1 = await approved_v1(studio)
    await studio.patch(v1, by_position(v1, 10), unit_cost="41.20")
    for statement in (
        "UPDATE quote_audit_trail SET details = '{}'::jsonb WHERE quote_id = :q",
        "DELETE FROM quote_audit_trail WHERE quote_id = :q",
    ):
        with pytest.raises(DBAPIError):
            await _sql(sessionmaker, studio.h.tenant, statement, q=v1["id"])
    async with tenant_session(studio.h.tenant, sessionmaker=sessionmaker) as s:
        kept = list(
            await s.scalars(
                select(QuoteAuditTrail.event).where(QuoteAuditTrail.quote_id == uuid.UUID(v1["id"]))
            )
        )
        quote = await s.scalar(select(Quote).where(Quote.id == uuid.UUID(v1["id"])))
    assert "quote.revision.created" in kept
    assert quote is not None
    assert quote.revision == 2


async def test_new_revision_only_from_an_approved_quote(studio: Studio, sessionmaker: Sm) -> None:  # noqa: F811
    q = await studio.quote("catalog_de", customer_id="100077")  # a draft
    with pytest.raises(DBAPIError, match="only be opened from an approved quote"):
        await _sql(
            sessionmaker, studio.h.tenant, "UPDATE quotes SET revision = 2 WHERE id = :q", q=q["id"]
        )
