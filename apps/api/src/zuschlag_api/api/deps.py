from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from zuschlag_api.core.auth import Principal, get_principal
from zuschlag_api.db.session import tenant_session


async def get_tenant_db(
    principal: Annotated[Principal, Depends(get_principal)],
) -> AsyncIterator[AsyncSession]:
    async with tenant_session(principal.tenant_id) as session:
        yield session


PrincipalDep = Annotated[Principal, Depends(get_principal)]
TenantDb = Annotated[AsyncSession, Depends(get_tenant_db)]
