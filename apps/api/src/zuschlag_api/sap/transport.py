"""Delivery of outbound IDocs to SAP.

Two standard ALE inbound paths are supported:

* ``file``: the XML is written into a directory that an SAP file port (WE21,
  port type "File") or the integration middleware polls. The file appears
  atomically (written under a temporary name, then renamed), so SAP never
  reads a half-written IDoc.
* ``http``: the XML is POSTed to an SAP "XML HTTP" port (SICF service
  ``/sap/bc/idoc_xml``) or to middleware such as SAP Integration Suite.

  If SAP answers with an ALEAUD01 acknowledgement, its status records are
  returned; status 51 (not posted) fails the delivery.

A probe reports whether the target is reachable and how long it took, for the
connection indicator in the UI.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal, Protocol

import httpx
from httpx._client import USE_CLIENT_DEFAULT, UseClientDefault

from zuschlag_api.core.config import Settings, get_settings
from zuschlag_api.sap.aleaud import ERROR, AckStatus, parse_aleaud
from zuschlag_api.sap.idoc_xml import IdocParseError


class TransportError(RuntimeError):
    """The IDoc could not be handed over to SAP."""


class SapRejectedError(TransportError):
    """SAP received the IDoc but did not post it (status 51)."""

    def __init__(self, statuses: list[AckStatus]) -> None:
        self.statuses = statuses
        self.reasons = [s.text or s.status for s in statuses if s.status == ERROR]
        super().__init__(f"SAP rejected the IDoc (status 51): {'; '.join(self.reasons)}")


@dataclass(frozen=True, slots=True)
class Receipt:
    reference: str
    # SAP's synchronous acknowledgement, if the port returns one (empty for file ports).
    statuses: tuple[AckStatus, ...] = ()


@dataclass(frozen=True, slots=True)
class Probe:
    reachable: bool
    latency_ms: float | None
    detail: str


TransportKind = Literal["file", "http"]


class SapTransport(Protocol):
    @property
    def kind(self) -> TransportKind: ...

    @property
    def target(self) -> str: ...

    async def send(self, filename: str, xml: bytes) -> Receipt:
        """Hand the IDoc over; returns a delivery reference for the audit trail."""
        ...

    async def probe(self) -> Probe: ...


class FilePortTransport:
    kind: Final = "file"

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.target = str(directory)

    async def send(self, filename: str, xml: bytes) -> Receipt:
        return Receipt(await asyncio.to_thread(self._write, filename, xml))

    def _write(self, filename: str, xml: bytes) -> str:
        final = self.directory / filename
        if final.exists():
            raise TransportError(f"{filename} already exists in the SAP outbound directory")
        tmp = self.directory / f".{filename}.part"
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tmp.open("xb") as fh:
                fh.write(xml)
                fh.flush()
                os.fsync(fh.fileno())
            tmp.rename(final)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise TransportError(f"cannot write to SAP outbound directory: {exc}") from exc
        return f"file:{final.name}"

    async def probe(self) -> Probe:
        return await asyncio.to_thread(self._probe)

    def _probe(self) -> Probe:
        start = time.perf_counter()
        ok = self.directory.is_dir() and os.access(self.directory, os.W_OK)
        latency = (time.perf_counter() - start) * 1000
        return Probe(ok, latency if ok else None, "writable" if ok else "directory not writable")


class HttpPortTransport:
    kind: Final = "http"

    def __init__(
        self,
        url: str,
        *,
        auth: tuple[str, str] | None = None,
        timeout_s: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url
        self.target = httpx.URL(url).host
        self._auth: httpx.Auth | UseClientDefault = (
            httpx.BasicAuth(*auth) if auth else USE_CLIENT_DEFAULT
        )
        self._timeout = timeout_s
        self._client = client

    def _http(self) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(timeout=self._timeout)

    async def send(self, filename: str, xml: bytes) -> Receipt:
        client = self._http()
        try:
            res = await client.post(
                self.url,
                content=xml,
                headers={"Content-Type": "application/xml; charset=utf-8"},
                auth=self._auth,
            )
        except httpx.HTTPError as exc:
            raise TransportError(f"SAP endpoint unreachable: {exc.__class__.__name__}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        statuses: list[AckStatus] = []
        if "xml" in res.headers.get("content-type", "") and res.content.strip():
            try:
                statuses = parse_aleaud(res.content)
            except IdocParseError as exc:
                raise TransportError(f"unreadable SAP acknowledgement: {exc}") from exc
        if any(s.status == ERROR for s in statuses):
            raise SapRejectedError(statuses)
        if not res.is_success:
            raise TransportError(f"SAP endpoint answered HTTP {res.status_code}")
        return Receipt(f"http:{res.status_code}:{filename}", tuple(statuses))

    async def probe(self) -> Probe:
        client = self._http()
        start = time.perf_counter()
        try:
            res = await client.head(self.url, auth=self._auth)
        except httpx.HTTPError as exc:
            return Probe(False, None, exc.__class__.__name__)
        finally:
            if self._client is None:
                await client.aclose()
        latency = (time.perf_counter() - start) * 1000
        # Any answer below 500 means the service is up (SAP answers HEAD with 405 or 200).
        ok = res.status_code < 500
        return Probe(ok, latency, f"HTTP {res.status_code}")


def transport_from_settings(settings: Settings) -> SapTransport | None:
    if settings.sap_outbound_transport == "file":
        assert settings.sap_outbound_dir is not None
        return FilePortTransport(settings.sap_outbound_dir)
    if settings.sap_outbound_transport == "http":
        assert settings.sap_outbound_url is not None
        auth = (
            (settings.sap_outbound_username, settings.sap_outbound_password.get_secret_value())
            if settings.sap_outbound_username and settings.sap_outbound_password
            else None
        )
        return HttpPortTransport(
            settings.sap_outbound_url, auth=auth, timeout_s=settings.sap_outbound_timeout_s
        )
    return None


@lru_cache
def get_sap_transport() -> SapTransport | None:
    """Process-wide transport (FastAPI dependency)."""
    return transport_from_settings(get_settings())
