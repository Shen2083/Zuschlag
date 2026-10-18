from __future__ import annotations

import hashlib
import hmac
import ipaddress

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


def pseudonymize_ip(ip: str | None, key: bytes) -> str | None:
    """Keyed SHA-256 (HMAC) of a normalised IP address, hex-encoded.

    A plain SHA-256 of an IPv4 address is reversible by enumerating all 2^32
    addresses; keying it with a secret makes it a pseudonym under GDPR Art. 4(5).
    """
    if not ip:
        return None
    try:
        normalised = ipaddress.ip_address(ip.strip()).compressed
    except ValueError:
        normalised = ip.strip().lower()
    return hmac.new(key, normalised.encode(), hashlib.sha256).hexdigest()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Conservative headers for a JSON API that is never rendered in a browser."""

    def __init__(self, app: object, *, hsts: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        headers.setdefault("Cache-Control", "no-store")
        if not request.url.path.startswith(("/docs", "/redoc")):
            headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
        if self._hsts:
            headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response
