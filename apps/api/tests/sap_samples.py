"""Builders for MATMAS05 / DEBMAS06 test payloads, derived from the fixture files."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "sap"
MATMAS_XML = (FIXTURES / "matmas05_shenai.xml").read_text(encoding="utf-8")
DEBMAS_XML = (FIXTURES / "debmas06_shenba.xml").read_text(encoding="utf-8")

MATMAS_DOCNUM = "0000000004711001"
DEBMAS_DOCNUM = "0000000004712001"
MAKTX_DE = "Shen AI Produktbeschreibung für Gehäuse"


def matmas(
    *,
    docnum: str = MATMAS_DOCNUM,
    matnr: str = "shenai",
    maktx_de: str = MAKTX_DE,
    brgew: str = "12.500",
    lvorm: str = "",
) -> bytes:
    xml = (
        MATMAS_XML.replace(MATMAS_DOCNUM, docnum)
        .replace("<MATNR>shenai</MATNR>", f"<MATNR>{matnr}</MATNR>")
        .replace(MAKTX_DE, maktx_de)
        .replace("<BRGEW>12.500</BRGEW>", f"<BRGEW>{brgew}</BRGEW>")
        .replace("<LVORM></LVORM>", f"<LVORM>{lvorm}</LVORM>")
    )
    return xml.encode()


def idoc_packet(*payloads: bytes, root: str = "MATMAS05") -> bytes:
    """Combine single-IDoc documents into one multi-IDoc packet."""
    bodies = []
    for p in payloads:
        text = p.decode()
        bodies.append(text[text.index("<IDOC") : text.rindex("</IDOC>") + len("</IDOC>")])
    return f'<?xml version="1.0" encoding="UTF-8"?><{root}>{"".join(bodies)}</{root}>'.encode()


def debmas(
    *,
    docnum: str = DEBMAS_DOCNUM,
    kunnr: str = "0000100042",
    zterm_10: str = "NT30",
    drop_channel_20: bool = False,
) -> bytes:
    xml = (
        DEBMAS_XML.replace(DEBMAS_DOCNUM, docnum)
        .replace("<KUNNR>0000100042</KUNNR>", f"<KUNNR>{kunnr}</KUNNR>")
        .replace("<ZTERM>NT30</ZTERM>", f"<ZTERM>{zterm_10}</ZTERM>")
    )
    if drop_channel_20:
        start = xml.index("<E1KNVVM", xml.index("<VTWEG>10</VTWEG>"))
        end = xml.index("</E1KNVVM>", start) + len("</E1KNVVM>")
        xml = xml[:start] + xml[end:]
    return xml.encode()
