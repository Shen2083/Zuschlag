"""Hardened reader for SAP IDoc XML (the format of the SAP "XML HTTP" port).

Security:
  * Parsing goes through `defusedxml` with DTDs forbidden outright, so external
    entities (XXE), entity expansion ("billion laughs") and external DTD
    fetches are all rejected before any data is processed.
  * Payload size is capped by the caller (see `Settings.sap_idoc_max_bytes`).

Performance:
  * IDoc packets can contain thousands of `<IDOC>` elements. They are streamed
    with `iterparse`, and each `<IDOC>` subtree is released as soon as it has
    been converted, so memory stays proportional to one IDoc, not the packet.

Namespaces (added by SAP PI/PO or CPI) are ignored: segments are matched by
local name.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import iterparse


class IdocParseError(ValueError):
    """The payload is not well-formed, safe IDoc XML of the expected type."""


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@dataclass(frozen=True, slots=True)
class Segment:
    """A namespace-free view of one IDoc segment (an XML element)."""

    name: str
    fields: dict[str, str]
    children: tuple[Segment, ...]

    def child(self, name: str) -> Segment | None:
        return next((c for c in self.children if c.name == name), None)

    def all(self, name: str) -> list[Segment]:
        return [c for c in self.children if c.name == name]


def _to_segment(elem: Element) -> Segment:
    fields: dict[str, str] = {}
    children: list[Segment] = []
    for child in elem:
        if len(child):  # has sub-elements => nested segment
            children.append(_to_segment(child))
            continue
        value = (child.text or "").strip()
        if value:  # SAP omits or blanks unset fields; treat both as absent
            fields[local_name(child.tag)] = value
    return Segment(local_name(elem.tag), fields, tuple(children))


def accept_basic_type(basic_type: str) -> Callable[[str], bool]:
    """Root names allowed for a basic type: the type itself (MATMAS05) or a
    customer extension in the Z/Y namespace (ZMATMAS05, ZMATMAS05_EXT, ...).
    The control record's IDOCTYP is checked separately and must be the basic type."""
    return lambda root: root == basic_type or (root[:1] in {"Z", "Y"} and basic_type in root)


def iter_idocs(payload: bytes, *, accept_root: Callable[[str], bool]) -> Iterator[Segment]:
    """Yield one `Segment` per `<IDOC>` element of an IDoc XML document."""
    events = iterparse(
        io.BytesIO(payload),
        events=("start", "end"),
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    )
    depth = 0
    found = 0
    try:
        for event, elem in events:
            if event == "start":
                depth += 1
                if depth == 1 and not accept_root(local_name(elem.tag)):
                    raise IdocParseError(f"unexpected root element <{local_name(elem.tag)}>")
                continue
            depth -= 1
            if depth == 1 and local_name(elem.tag) == "IDOC":
                found += 1
                yield _to_segment(elem)
                elem.clear()  # free the subtree; the root keeps only an empty shell
    except (ParseError, DefusedXmlException) as exc:
        raise IdocParseError(f"rejected XML: {exc.__class__.__name__}: {exc}") from exc
    if found == 0:
        raise IdocParseError("document contains no <IDOC> element")
