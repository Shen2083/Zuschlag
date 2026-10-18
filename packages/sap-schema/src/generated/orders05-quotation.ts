/* eslint-disable */
// AUTO-GENERATED from schemas/ by scripts/generate.mjs — do not edit.

/**
 * YYYYMMDD
 */
export type SapDate = string;
/**
 * HHMMSS
 */
export type SapTime = string;
export type IsoCurrency = string;
/**
 * Decimal quantity, '.' separator, up to 3 decimals (MENGE CHAR 15)
 */
export type SapQuantity = string;
/**
 * ISO unit of measure, e.g. PCE, HUR, KGM, MTR
 */
export type IsoUnit = string;
/**
 * Decimal amount, optional leading '-', up to 4 decimals (CHAR 18)
 */
export type SapAmount = string;

/**
 * Inbound ORDERS05 IDoc (message type ORDERS) that creates an SD quotation (order type from E1EDK14 QUALF 012, e.g. AG). This is the subset of segments Zuschlag.ai populates. All values are strings, as in the IDoc flat format. Verify field lengths against transaction WE60 for your SAP release.
 */
export interface Orders05Quotation {
  EDI_DC40: ControlRecord;
  E1EDK01: E1EDK01;
  /**
   * @minItems 1
   */
  E1EDK14: [E1EDK14, ...E1EDK14[]];
  E1EDK03?: E1EDK03[];
  /**
   * @minItems 1
   */
  E1EDKA1: [E1EDKA1, ...E1EDKA1[]];
  E1EDK02?: E1EDK02[];
  /**
   * @minItems 1
   */
  E1EDP01: [E1EDP01, ...E1EDP01[]];
}
export interface ControlRecord {
  TABNAM: "EDI_DC40";
  /**
   * SAP client
   */
  MANDT: string;
  DOCNUM?: string;
  /**
   * 2 = inbound to SAP
   */
  DIRECT: "2";
  IDOCTYP: "ORDERS05";
  MESTYP: "ORDERS";
  SNDPOR: string;
  /**
   * Partner type, LS = logical system
   */
  SNDPRT: "LS" | "KU";
  SNDPRN: string;
  RCVPOR: string;
  RCVPRT: "LS";
  RCVPRN: string;
  CREDAT: SapDate;
  CRETIM: SapTime;
}
/**
 * Document header general data
 */
export interface E1EDK01 {
  CURCY: IsoCurrency;
  /**
   * Payment terms key
   */
  ZTERM?: string;
  /**
   * External document number (Zuschlag quote number)
   */
  BELNR?: string;
}
/**
 * Organisational data. 006 division, 007 distribution channel, 008 sales organisation, 012 SD document type
 */
export interface E1EDK14 {
  QUALF: "006" | "007" | "008" | "012";
  ORGID: string;
}
/**
 * Header dates (IDDAT qualifier, e.g. 002 requested delivery date)
 */
export interface E1EDK03 {
  IDDAT: string;
  DATUM: SapDate;
}
/**
 * Header partner. AG sold-to, WE ship-to, RE bill-to, RG payer
 */
export interface E1EDKA1 {
  PARVW: "AG" | "WE" | "RE" | "RG";
  /**
   * SAP customer number (KUNNR)
   */
  PARTN: string;
  NAME1?: string;
}
/**
 * Header reference. QUALF 001 = customer purchase order / RFQ reference
 */
export interface E1EDK02 {
  QUALF: string;
  BELNR: string;
  DATUM?: SapDate;
}
/**
 * Item general data
 */
export interface E1EDP01 {
  /**
   * Item number
   */
  POSEX: string;
  MENGE: SapQuantity;
  MENEE: IsoUnit;
  /**
   * @minItems 1
   */
  E1EDP19: [E1EDP19, ...E1EDP19[]];
  E1EDP05?: E1EDP05[];
  E1EDP20?: E1EDP20[];
}
/**
 * Item object identification. 002 = material number (MATNR) of the selling company, 001 = customer material number
 */
export interface E1EDP19 {
  QUALF: "001" | "002";
  IDTNR: string;
  /**
   * Short text
   */
  KTEXT?: string;
}
/**
 * Item condition, e.g. PR00 price or a surcharge (Zuschlag) condition type
 */
export interface E1EDP05 {
  /**
   * + surcharge, - discount
   */
  ALCKZ?: "+" | "-";
  KSCHL: string;
  BETRG?: SapAmount;
  KRATE?: SapAmount;
  /**
   * Percentage
   */
  KPERC?: string;
}
/**
 * Item schedule line
 */
export interface E1EDP20 {
  WMENG: SapQuantity;
  EDATU?: SapDate;
}
