"""Schema-level tenancy guards, checked statically against the ORM metadata."""

from __future__ import annotations

from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint

from zuschlag_api import models  # noqa: F401
from zuschlag_api.db.base import Base

TENANT_ROOT = "tenants"


def test_every_table_has_non_null_tenant_id() -> None:
    for table in Base.metadata.sorted_tables:
        assert "tenant_id" in table.c, f"{table.name} lacks tenant_id"
        assert not table.c.tenant_id.nullable, f"{table.name}.tenant_id is nullable"


def test_cross_table_foreign_keys_include_tenant_id() -> None:
    """A row may only reference rows of its own tenant: every FK between domain
    tables must be composite and carry tenant_id on both sides."""
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_key_constraints:
            if fk.referred_table.name == TENANT_ROOT:
                continue
            local = [c.name for c in fk.columns]
            remote = [e.column.name for e in fk.elements]
            message = f"{table.name} -> {fk.referred_table.name} FK {local} is not tenant-scoped"
            assert "tenant_id" in local, message
            assert "tenant_id" in remote, message


def test_referenced_tables_expose_tenant_composite_key() -> None:
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_key_constraints:
            if fk.referred_table.name == TENANT_ROOT:
                continue
            targets = {e.column.name for e in fk.elements}
            uniques = [
                {c.name for c in uc.columns}
                for uc in fk.referred_table.constraints
                if isinstance(uc, UniqueConstraint | PrimaryKeyConstraint)
            ]
            assert targets in uniques
