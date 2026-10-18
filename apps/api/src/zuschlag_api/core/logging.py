"""Structured JSON logs with personal data masked (GDPR art. 5(1)(c), 25).

Every line passes through `mask_pii` before it is written: the message, every
`extra` field and the traceback. Masked are e-mail addresses, phone numbers,
IP addresses, IBANs, the values of search-type query parameters, and whole
values of fields known to hold personal data (contact name, e-mail, phone,
RFQ text). Business identifiers (DOCNUM, KUNNR, MATNR, UUIDs, hashes) stay
readable, since operations depend on them.

uvicorn's own loggers are routed through the same formatter: its access log
would otherwise write client IPs and query strings unmasked.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

_STD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}

MASK = "***"

# Field names whose whole value is personal data.
PII_KEYS = frozenset(
    {
        "contact_name",
        "contact_email",
        "contact_phone",
        "email",
        "phone",
        "telf1",
        "name",
        "first_name",
        "last_name",
        "raw_text",
        "body_text",
        "client_ip",
        "ip",
        "iban",
    }
)
# Query parameters that carry free text typed by users (names, e-mails).
_QUERY = re.compile(r"([?&](?:q|search|query|email|name|contact)=)[^&\s\"']*", re.IGNORECASE)
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.([A-Za-z]{2,})\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,3})?\b")
_IPV4 = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}\b")
# Four or more groups, or a "::" compression: never a clock time like 17:31:51.
_IPV6 = re.compile(
    r"\b(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b"
    r"|(?<![\w:])(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}\b"
)
# Phone numbers: +49 / 0049 / 0 prefix and 7-15 digits in total. Numbers with three
# leading zeros are SAP keys (KUNNR, DOCNUM), never phone numbers.
_PHONE = re.compile(r"(?<![\w.-])(?:\+|00(?!0)|0(?!00))\d(?:[ /()-]?\d){5,13}(?![\w-])")


# PostgreSQL and asyncpg echo row values in error messages; SQLAlchemy's
# hide_parameters cannot reach those, so they are masked here.
_DB_ECHOES = (
    (re.compile(r"(invalid input for query argument \$\d+: )'(?:[^'\\]|\\.)*'"), r"\1***"),
    (re.compile(r'(invalid input syntax for type [\w ]+: )"[^"]*"'), r"\1***"),
    (re.compile(r"(Key \([^)]*\)=)\((?:[^()]|\([^()]*\))*\)"), r"\1(***)"),
    (re.compile(r"(Failing row contains )\((?:[^()]|\([^()]*\))*\)"), r"\1(***)"),
)


def _mask_text(text: str) -> str:
    for pattern, replacement in _DB_ECHOES:
        text = pattern.sub(replacement, text)
    text = _QUERY.sub(lambda m: m.group(1) + MASK, text)
    text = _EMAIL.sub(lambda m: f"{m.group(1)}{MASK}@{MASK}.{m.group(2)}", text)
    text = _IBAN.sub(lambda m: m.group(0)[:4] + MASK, text)
    text = _IPV4.sub(lambda m: f"{m.group(1)}.{m.group(2)}.x.x", text)
    text = _IPV6.sub("ipv6:" + MASK, text)
    return _PHONE.sub(lambda m: m.group(0)[:3] + MASK, text)


def mask_pii(value: Any, key: str | None = None) -> Any:
    """Recursively mask personal data in a log value."""
    if key is not None and key.lower() in PII_KEYS and value not in (None, ""):
        return MASK
    if isinstance(value, str):
        return _mask_text(value)
    if isinstance(value, Mapping):
        return {k: mask_pii(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [mask_pii(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    """One JSON object per line; `extra={...}` fields included, personal data masked."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(mask_pii(payload), default=lambda o: mask_pii(str(o)))


UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # uvicorn installs its own (unmasked) handlers and stops propagation: replace them.
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers[:] = []
        logger.propagate = True
