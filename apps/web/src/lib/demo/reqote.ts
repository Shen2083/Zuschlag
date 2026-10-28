/**
 * ORDERS05 / REQOTE rendering for the static demo: a port of apps/api
 * sap/reqote.py with the same byte layout (UTF-8, CRLF, 4-space indent, no
 * final newline, SEGMENT on the control record, segment on data segments,
 * empty optional fields omitted). test/demo-reqote.test.ts compares it with
 * the interface contract quote_as_output.txt byte for byte.
 */
export interface OutboundProfile {
  mandt: string;
  docrel?: string;
  status?: string;
  direct?: string;
  sender_port: string;
  sender_partner_type?: string;
  sender_partner: string;
  receiver_port: string;
  receiver_partner_type?: string;
  receiver_partner: string;
  vendor_number: string;
  vendor_name: string;
}

export interface SoldTo {
  partn: string;
  name1: string;
  name2?: string | null;
  stras?: string | null;
  ort01?: string | null;
  pstlz?: string | null;
  land1?: string | null;
}

export interface ReqoteItem {
  posex: number;
  menge: string; // decimal string
  menee: string;
  idnlf: string;
  ktext: string;
}

export interface ReqoteDocument {
  docnum: string;
  belnr: string;
  curcy: string;
  zterm: string;
  soldTo: SoldTo;
  items: ReqoteItem[];
}

const CRLF = "\r\n";
const INDENT = "    ";

function escape(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

export function formatPosex(position: number): string {
  return String(position).padStart(5, "0");
}

/** Three decimals, rounded half up (SAP MENGE). */
export function formatMenge(value: string): string {
  const [int = "0", frac = ""] = value.split(".");
  const digits = BigInt(int + frac.padEnd(3, "0").slice(0, 3));
  const roundUp = frac.length > 3 && Number(frac[3]) >= 5;
  const units = (digits + (roundUp ? 1n : 0n)).toString().padStart(4, "0");
  return `${units.slice(0, -3)}.${units.slice(-3)}`;
}

export function renderReqote(doc: ReqoteDocument, profile: OutboundProfile): string {
  const lines: string[] = ['<?xml version="1.0" encoding="UTF-8"?>', "<ORDERS05>"];
  const at = (depth: number) => INDENT.repeat(depth);
  const field = (depth: number, name: string, value: string | null | undefined) => {
    if (value === null || value === undefined || value === "") return;
    lines.push(`${at(depth)}<${name}>${escape(value)}</${name}>`);
  };

  lines.push(`${at(1)}<IDOC BEGIN="1">`);
  lines.push(`${at(2)}<EDI_DC40 SEGMENT="1">`);
  field(3, "TABNAM", "EDI_DC40");
  field(3, "MANDT", profile.mandt);
  field(3, "DOCNUM", doc.docnum);
  field(3, "DOCREL", profile.docrel ?? "750");
  field(3, "STATUS", profile.status ?? "30");
  field(3, "DIRECT", profile.direct ?? "1");
  field(3, "IDOCTYP", "ORDERS05");
  field(3, "MESTYP", "REQOTE");
  field(3, "SNDPOR", profile.sender_port);
  field(3, "SNDPRT", profile.sender_partner_type ?? "LS");
  field(3, "SNDPRN", profile.sender_partner);
  field(3, "RCVPOR", profile.receiver_port);
  field(3, "RCVPRT", profile.receiver_partner_type ?? "LS");
  field(3, "RCVPRN", profile.receiver_partner);
  lines.push(`${at(2)}</EDI_DC40>`);

  lines.push(`${at(2)}<E1EDK01 segment="1">`);
  field(3, "ACTION", "004");
  field(3, "CURCY", doc.curcy);
  field(3, "ZTERM", doc.zterm);
  field(3, "BELNR", doc.belnr);
  lines.push(`${at(2)}</E1EDK01>`);

  const s = doc.soldTo;
  lines.push(`${at(2)}<E1EDKA1 segment="1">`);
  field(3, "PARVW", "AG");
  field(3, "PARTN", s.partn);
  field(3, "NAME1", s.name1);
  field(3, "NAME2", s.name2);
  field(3, "STRAS", s.stras);
  field(3, "ORT01", s.ort01);
  field(3, "PSTLZ", s.pstlz);
  field(3, "LAND1", s.land1);
  lines.push(`${at(2)}</E1EDKA1>`);

  lines.push(`${at(2)}<E1EDKA1 segment="1">`);
  field(3, "PARVW", "LF");
  field(3, "PARTN", profile.vendor_number);
  field(3, "NAME1", profile.vendor_name);
  lines.push(`${at(2)}</E1EDKA1>`);

  for (const item of doc.items) {
    lines.push(`${at(2)}<E1EDP01 segment="1">`);
    field(3, "POSEX", formatPosex(item.posex));
    field(3, "MENGE", formatMenge(item.menge));
    field(3, "MENEE", item.menee);
    lines.push(`${at(3)}<E1EDP19 segment="1">`);
    field(4, "QUALF", "002");
    field(4, "IDNLF", item.idnlf);
    field(4, "KTEXT", item.ktext);
    lines.push(`${at(3)}</E1EDP19>`);
    lines.push(`${at(2)}</E1EDP01>`);
  }

  lines.push(`${at(1)}</IDOC>`);
  lines.push("</ORDERS05>");
  return lines.join(CRLF);
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}
