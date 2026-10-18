"""ORM-level tenancy guards (defence in depth on top of PostgreSQL RLS).

* SELECTs touching a `TenantScoped` model are automatically filtered to the
  session's tenant, and refused outright when the session has no tenant.
* Flushes assign the session tenant to new rows, and refuse rows whose
  `tenant_id` belongs to a different tenant or was changed after load.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from zuschlag_api.db.base import TenantScoped


class TenancyViolationError(RuntimeError):
    """Raised when code tries to read or write across tenant boundaries."""


def install(session_cls: type[Session], *, tenant_key: str, system_key: str) -> None:
    @event.listens_for(session_cls, "do_orm_execute")
    def _scope_queries(state: ORMExecuteState) -> None:
        if not (state.is_select or state.is_update or state.is_delete):
            return
        if state.is_column_load or state.is_relationship_load:
            return  # parent query was already scoped
        info = state.session.info
        tenant_id = info.get(tenant_key)
        if tenant_id is None:
            if info.get(system_key):
                return
            if _touches_tenant_tables(state):
                raise TenancyViolationError(
                    "tenant-scoped query on a session without tenant_id; "
                    "use tenant_session() (or system_session() for system tasks)"
                )
            return
        state.statement = state.statement.options(
            with_loader_criteria(
                TenantScoped,
                lambda cls: cls.tenant_id == tenant_id,
                include_aliases=True,
            )
        )

    @event.listens_for(session_cls, "before_flush")
    def _check_writes(session: Session, flush_context: Any, instances: Any) -> None:
        tenant_id = session.info.get(tenant_key)
        system = bool(session.info.get(system_key))
        for obj in session.new:
            if not isinstance(obj, TenantScoped):
                continue
            obj_tenant: uuid.UUID | None = obj.tenant_id
            if obj_tenant is None:
                if tenant_id is None:
                    raise TenancyViolationError(f"{type(obj).__name__} has no tenant_id")
                obj.tenant_id = tenant_id
            elif tenant_id is not None and obj_tenant != tenant_id:
                raise TenancyViolationError(
                    f"refusing to insert {type(obj).__name__} for a foreign tenant"
                )
            elif tenant_id is None and not system:
                raise TenancyViolationError("insert on a session without tenant_id")
        for obj in session.dirty:
            if isinstance(obj, TenantScoped):
                state = inspect(obj)
                if state is not None and state.attrs.tenant_id.history.deleted:
                    raise TenancyViolationError("tenant_id is immutable")


def _touches_tenant_tables(state: ORMExecuteState) -> bool:
    return any(issubclass(mapper.class_, TenantScoped) for mapper in state.all_mappers)
