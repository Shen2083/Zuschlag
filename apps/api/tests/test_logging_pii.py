"""Personal data never reaches the log output (GDPR data minimisation)."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.rfq_support import rfq_text
from tests.test_integration_rfq_pipeline import Harness, h  # noqa: F401 — fixture
from zuschlag_api.core.logging import UVICORN_LOGGERS, JsonFormatter, configure_logging, mask_pii
from zuschlag_api.db.session import tenant_session


@pytest.fixture
def log() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("zuschlag.test.pii")
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    yield logger, stream
    logger.removeHandler(handler)


PERSONAL = {
    "e-mail": "m.weber@rz-nord.de",
    "phone (TELF1 from Customerxml.txt)": "0891234567",
    "phone, international": "+49 40 123456-0",
    "IPv4": "203.0.113.9",
    "IPv6": "2001:db8:85a3::8a2e:370:7334",
    "IBAN": "DE89 3704 0044 0532 0130 00",
}


@pytest.mark.parametrize("kind", list(PERSONAL), ids=list(PERSONAL))
def test_personal_data_in_messages_is_masked(
    log: tuple[logging.Logger, io.StringIO], kind: str
) -> None:
    logger, stream = log
    logger.info("contact %s for quote AN-20261018-0601C3", PERSONAL[kind])
    out = stream.getvalue()
    assert PERSONAL[kind] not in out
    assert "AN-20261018-0601C3" in out


def test_extra_fields_and_tracebacks_are_masked(log: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = log
    try:
        raise ValueError("customer m.weber@rz-nord.de not found")
    except ValueError:
        logger.exception(
            "lookup failed",
            extra={
                "contact_name": "Markus Weber",
                "context": {"contact_email": "m.weber@rz-nord.de", "kunnr": "0000100042"},
                "raw_text": "Sehr geehrte Damen und Herren, ... Markus Weber",
            },
        )
    line = json.loads(stream.getvalue())
    assert "Markus Weber" not in stream.getvalue()
    assert "rz-nord" not in stream.getvalue()
    assert line["contact_name"] == "***"
    assert line["raw_text"] == "***"
    assert line["context"]["kunnr"] == "0000100042"  # business keys stay readable
    assert "ValueError" in line["exc"]


def test_access_log_hides_client_ip_and_search_terms(
    log: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = log
    # uvicorn's access log format: client, method, path, HTTP version, status.
    logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "203.0.113.9:51234",
        "GET",
        "/api/v1/customers?q=Anja%20Kr%C3%BCger&limit=50",
        "1.1",
        200,
    )
    out = json.loads(stream.getvalue())["msg"]
    assert "203.0.113.9" not in out
    assert "Anja" not in out
    assert out.startswith("203.0.x.x:51234")
    assert "q=***&limit=50" in out


@pytest.mark.parametrize(
    "message",
    [
        "invalid input for query argument $1: 'Markus Weber' ('str' object cannot be interpreted)",
        'invalid input syntax for type integer: "Markus Weber"',
        "DETAIL:  Key (tenant_id, name1)=(5e1d0c3a, Markus Weber) already exists.",
        "DETAIL:  Failing row contains (5e1d0c3a, Markus Weber, null).",
    ],
)
def test_database_errors_do_not_echo_row_values(message: str) -> None:
    assert "Markus Weber" not in mask_pii(message)


@pytest.mark.parametrize(
    "keep",
    [
        "0000000000987654",  # DOCNUM
        "0000100042",  # KUNNR
        "2026-10-18T17:31:51.524+00:00",  # timestamps
        "1d10c131760fc930d23bea24703e4dccbce8adf15288aa5b0b592cfdd7a739d1",  # SHA-256
        "88310212-a164-4121-8e0d-efddaebdc78e",  # UUID
        "PT-CAS-125HD",  # MATNR
        "1.785,00 EUR",
    ],
)
def test_business_identifiers_are_not_over_masked(keep: str) -> None:
    assert mask_pii(f"value {keep} end") == f"value {keep} end"


def test_uvicorn_loggers_go_through_the_masking_formatter() -> None:
    configure_logging("INFO")
    root_handlers = logging.getLogger().handlers
    assert all(isinstance(handler.formatter, JsonFormatter) for handler in root_handlers)
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        assert logger.handlers == []
        assert logger.propagate


# --------------------------------------------------------------------------- #
# Whole pipeline: an RFQ full of personal data leaves no trace in the logs
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_pipeline_logs_carry_no_personal_data(h: Harness) -> None:  # noqa: F811
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    sql = logging.getLogger("sqlalchemy.engine")
    sql.setLevel(logging.INFO)  # worst case: someone switched on SQL logging
    try:
        h.answer_with("rack_de")
        res = await h.generate(rfq_text("rack_de"))
        assert res.status_code == 201
        # A failing statement: its error message must not echo the bound values either.
        async with tenant_session(h.tenant) as s:
            with pytest.raises(DBAPIError) as exc:
                await s.execute(
                    text("SELECT CAST(:v AS integer)"), {"v": "Markus Weber m.weber@rz-nord.de"}
                )
            logging.getLogger("zuschlag.test").error("query failed: %s", exc.value)
    finally:
        sql.setLevel(logging.WARNING)
        root.removeHandler(handler)
        root.setLevel(previous)

    out = stream.getvalue()
    assert "llm.completion" in out  # the logs were really captured
    assert "INSERT INTO quotes" in out
    for personal in ("Markus Weber", "m.weber@rz-nord.de", "+49 40 123456-0", "203.0.113.9"):
        assert personal not in out, personal
