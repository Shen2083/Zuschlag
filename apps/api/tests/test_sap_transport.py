"""Outbound IDoc transports (file port, XML-HTTP port)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from zuschlag_api.core.config import Settings
from zuschlag_api.sap.transport import (
    FilePortTransport,
    HttpPortTransport,
    TransportError,
    transport_from_settings,
)


def names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


XML = b'<?xml version="1.0" encoding="UTF-8"?>\r\n<ORDERS05/>'


async def test_file_port_writes_atomically_and_never_overwrites(tmp_path: Path) -> None:
    port = FilePortTransport(tmp_path)
    assert await port.send("REQOTE_1.xml", XML) == "file:REQOTE_1.xml"
    assert (tmp_path / "REQOTE_1.xml").read_bytes() == XML
    with pytest.raises(TransportError, match="already exists"):
        await port.send("REQOTE_1.xml", b"other")
    assert (tmp_path / "REQOTE_1.xml").read_bytes() == XML
    assert names(tmp_path) == ["REQOTE_1.xml"]
    assert (await port.probe()).reachable


async def test_file_port_probe_reports_missing_directory(tmp_path: Path) -> None:
    probe = await FilePortTransport(tmp_path / "nope").probe()
    assert (probe.reachable, probe.latency_ms) == (False, None)


async def test_http_port_posts_xml_with_basic_auth() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200 if request.method == "POST" else 405)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    port = HttpPortTransport(
        "https://sap.example.eu/sap/bc/idoc_xml?sap-client=800",
        auth=("RFC_USER", "s3cret"),
        client=client,
    )
    assert await port.send("REQOTE_1.xml", XML) == "http:200:REQOTE_1.xml"
    post = seen[0]
    assert post.content == XML
    assert post.headers["content-type"] == "application/xml; charset=utf-8"
    assert post.headers["authorization"].startswith("Basic ")
    probe = await port.probe()  # SAP answers HEAD with 405: the service is up
    assert probe.reachable
    assert probe.latency_ms is not None


@pytest.mark.parametrize("status", [401, 500, 503])
async def test_http_port_error_status_is_a_transport_error(status: int) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status)))
    port = HttpPortTransport("https://sap.example.eu/idoc", client=client)
    with pytest.raises(TransportError, match=str(status)):
        await port.send("REQOTE_1.xml", XML)


async def test_http_port_unreachable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    port = HttpPortTransport(
        "https://sap.example.eu/idoc", client=httpx.AsyncClient(transport=httpx.MockTransport(boom))
    )
    with pytest.raises(TransportError, match="unreachable"):
        await port.send("REQOTE_1.xml", XML)
    assert not (await port.probe()).reachable


def test_settings_select_and_validate_transport(tmp_path: Path) -> None:
    assert transport_from_settings(Settings()) is None
    file_port = transport_from_settings(
        Settings(sap_outbound_transport="file", sap_outbound_dir=tmp_path)
    )
    assert file_port is not None
    assert file_port.kind == "file"
    with pytest.raises(ValueError, match="SAP_OUTBOUND_DIR"):
        Settings(sap_outbound_transport="file")
    with pytest.raises(ValueError, match="must use https"):
        Settings(sap_outbound_transport="http", sap_outbound_url="http://sap.example.eu/idoc")
