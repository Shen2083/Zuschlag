"""Request principal (who is calling, for which tenant).

`dev_headers` mode trusts `X-Tenant-ID` / `X-Actor-ID` and exists only for
local development; Settings refuses it in production. Production must use
`oidc`, which is a deliberate stub until the identity provider is chosen
(e.g. Entra ID or Keycloak hosted in the EU).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from zuschlag_api.core.config import Settings, get_settings
from zuschlag_api.core.security import pseudonymize_ip


@dataclass(frozen=True, slots=True)
class Principal:
    tenant_id: uuid.UUID
    actor_id: str
    ip_sha256: str | None


def get_principal(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_actor_id: Annotated[str | None, Header()] = None,
) -> Principal:
    if settings.auth_mode != "dev_headers":
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "OIDC authentication not configured")
    if not x_tenant_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing X-Tenant-ID")
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Tenant-ID must be a UUID") from exc
    actor_id = (x_actor_id or "dev-user").strip()[:128]
    client_ip = request.client.host if request.client else None
    key = settings.audit_ip_hmac_key.get_secret_value().encode()
    return Principal(
        tenant_id=tenant_id, actor_id=actor_id, ip_sha256=pseudonymize_ip(client_ip, key)
    )
