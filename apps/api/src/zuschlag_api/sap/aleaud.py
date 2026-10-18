"""ALEAUD01 audit messages: SAP's acknowledgement of IDocs we sent.

The receiving SAP system reports what became of each IDoc as status records
(E1ADHDR/E1STATE), for example

* 06  translation OK: received and syntactically valid
* 53  application document posted (E1PRTOB names the document created)
* 51  application document not posted (error, STATXT says why)

Parsed with defusedxml like every other inbound XML (no DTDs, no entities).
"""

from __future__ import annotations

from dataclasses import dataclass

from defusedxml.ElementTree import fromstring

from zuschlag_api.sap.idoc_xml import IdocParseError

POSTED = "53"
ERROR = "51"


@dataclass(frozen=True, slots=True)
class AckStatus:
    docnum: str  # our outbound DOCNUM the status refers to
    status: str
    text: str | None
    object_key: str | None  # e.g. the SAP quotation number created (status 53)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "docnum": self.docnum,
            "status": self.status,
            "text": self.text,
            "object_key": self.object_key,
        }


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_aleaud(payload: bytes) -> list[AckStatus]:
    try:
        root = fromstring(payload)
    except Exception as exc:  # defusedxml raises several types for unsafe or broken XML
        raise IdocParseError(f"invalid ALEAUD XML: {exc.__class__.__name__}") from exc
    if _local(root.tag) != "ALEAUD01":
        raise IdocParseError(f"expected ALEAUD01, got {_local(root.tag)}")
    out: list[AckStatus] = []
    for state in root.iter():
        if _local(state.tag) != "E1STATE":
            continue
        fields = {_local(c.tag): (c.text or "").strip() for c in state}
        status = fields.get("STATUS", "")
        if not (len(status) == 2 and status.isdigit()):
            raise IdocParseError(f"invalid IDoc status {status!r}")
        prtob = next((c for c in state if _local(c.tag) == "E1PRTOB"), None)
        object_key = None
        if prtob is not None:
            object_key = next(
                ((c.text or "").strip() for c in prtob if _local(c.tag) == "OBJKEY"), None
            )
        out.append(
            AckStatus(
                docnum=fields.get("DOCNUM", "").zfill(16),
                status=status,
                text=fields.get("STATXT") or None,
                object_key=object_key or None,
            )
        )
    return out
