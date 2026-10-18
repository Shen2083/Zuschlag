/* eslint-disable */
// AUTO-GENERATED from schemas/ by scripts/generate.mjs — do not edit.

export const schema = {
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://schemas.zuschlag.ai/sap/idoc/orders05-quotation/v1.json",
  "title": "Orders05Quotation",
  "description": "Inbound ORDERS05 IDoc (message type ORDERS) that creates an SD quotation (order type from E1EDK14 QUALF 012, e.g. AG). This is the subset of segments Zuschlag.ai populates. All values are strings, as in the IDoc flat format. Verify field lengths against transaction WE60 for your SAP release.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "EDI_DC40",
    "E1EDK01",
    "E1EDK14",
    "E1EDKA1",
    "E1EDP01"
  ],
  "properties": {
    "EDI_DC40": {
      "$ref": "#/$defs/ControlRecord"
    },
    "E1EDK01": {
      "$ref": "#/$defs/E1EDK01"
    },
    "E1EDK14": {
      "type": "array",
      "minItems": 1,
      "items": {
        "$ref": "#/$defs/E1EDK14"
      },
      "contains": {
        "type": "object",
        "properties": {
          "QUALF": {
            "const": "012"
          }
        }
      }
    },
    "E1EDK03": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/E1EDK03"
      }
    },
    "E1EDKA1": {
      "type": "array",
      "minItems": 1,
      "items": {
        "$ref": "#/$defs/E1EDKA1"
      },
      "contains": {
        "type": "object",
        "properties": {
          "PARVW": {
            "const": "AG"
          }
        }
      }
    },
    "E1EDK02": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/E1EDK02"
      }
    },
    "E1EDP01": {
      "type": "array",
      "minItems": 1,
      "items": {
        "$ref": "#/$defs/E1EDP01"
      }
    }
  },
  "$defs": {
    "SapDate": {
      "description": "YYYYMMDD",
      "type": "string",
      "pattern": "^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$"
    },
    "SapTime": {
      "description": "HHMMSS",
      "type": "string",
      "pattern": "^([01][0-9]|2[0-3])[0-5][0-9][0-5][0-9]$"
    },
    "SapQuantity": {
      "description": "Decimal quantity, '.' separator, up to 3 decimals (MENGE CHAR 15)",
      "type": "string",
      "pattern": "^[0-9]{1,11}(\\.[0-9]{1,3})?$",
      "maxLength": 15
    },
    "SapAmount": {
      "description": "Decimal amount, optional leading '-', up to 4 decimals (CHAR 18)",
      "type": "string",
      "pattern": "^-?[0-9]{1,13}(\\.[0-9]{1,4})?$",
      "maxLength": 18
    },
    "IsoCurrency": {
      "type": "string",
      "pattern": "^[A-Z]{3}$"
    },
    "IsoUnit": {
      "description": "ISO unit of measure, e.g. PCE, HUR, KGM, MTR",
      "type": "string",
      "pattern": "^[A-Z0-9]{2,3}$"
    },
    "ControlRecord": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "TABNAM",
        "MANDT",
        "DIRECT",
        "IDOCTYP",
        "MESTYP",
        "SNDPOR",
        "SNDPRT",
        "SNDPRN",
        "RCVPOR",
        "RCVPRT",
        "RCVPRN",
        "CREDAT",
        "CRETIM"
      ],
      "properties": {
        "TABNAM": {
          "const": "EDI_DC40"
        },
        "MANDT": {
          "description": "SAP client",
          "type": "string",
          "pattern": "^[0-9]{3}$"
        },
        "DOCNUM": {
          "type": "string",
          "pattern": "^[0-9]{1,16}$"
        },
        "DIRECT": {
          "description": "2 = inbound to SAP",
          "const": "2"
        },
        "IDOCTYP": {
          "const": "ORDERS05"
        },
        "MESTYP": {
          "const": "ORDERS"
        },
        "SNDPOR": {
          "type": "string",
          "minLength": 1,
          "maxLength": 10
        },
        "SNDPRT": {
          "description": "Partner type, LS = logical system",
          "enum": [
            "LS",
            "KU"
          ]
        },
        "SNDPRN": {
          "type": "string",
          "minLength": 1,
          "maxLength": 10
        },
        "RCVPOR": {
          "type": "string",
          "minLength": 1,
          "maxLength": 10
        },
        "RCVPRT": {
          "enum": [
            "LS"
          ]
        },
        "RCVPRN": {
          "type": "string",
          "minLength": 1,
          "maxLength": 10
        },
        "CREDAT": {
          "$ref": "#/$defs/SapDate"
        },
        "CRETIM": {
          "$ref": "#/$defs/SapTime"
        }
      }
    },
    "E1EDK01": {
      "description": "Document header general data",
      "type": "object",
      "additionalProperties": false,
      "required": [
        "CURCY"
      ],
      "properties": {
        "CURCY": {
          "$ref": "#/$defs/IsoCurrency"
        },
        "ZTERM": {
          "description": "Payment terms key",
          "type": "string",
          "maxLength": 17
        },
        "BELNR": {
          "description": "External document number (Zuschlag quote number)",
          "type": "string",
          "maxLength": 35
        }
      }
    },
    "E1EDK14": {
      "description": "Organisational data. 006 division, 007 distribution channel, 008 sales organisation, 012 SD document type",
      "type": "object",
      "additionalProperties": false,
      "required": [
        "QUALF",
        "ORGID"
      ],
      "properties": {
        "QUALF": {
          "enum": [
            "006",
            "007",
            "008",
            "012"
          ]
        },
        "ORGID": {
          "type": "string",
          "minLength": 1,
          "maxLength": 35
        }
      }
    },
    "E1EDK03": {
      "description": "Header dates (IDDAT qualifier, e.g. 002 requested delivery date)",
      "type": "object",
      "additionalProperties": false,
      "required": [
        "IDDAT",
        "DATUM"
      ],
      "properties": {
        "IDDAT": {
          "type": "string",
          "pattern": "^[0-9]{3}$"
        },
        "DATUM": {
          "$ref": "#/$defs/SapDate"
        }
      }
    },
    "E1EDKA1": {
      "description": "Header partner. AG sold-to, WE ship-to, RE bill-to, RG payer",
      "type": "object",
      "additionalProperties": false,
      "required": [
        "PARVW",
        "PARTN"
      ],
      "properties": {
        "PARVW": {
          "enum": [
            "AG",
            "WE",
            "RE",
            "RG"
          ]
        },
        "PARTN": {
          "description": "SAP customer number (KUNNR)",
          "type": "string",
          "minLength": 1,
          "maxLength": 17
        },
        "NAME1": {
          "type": "string",
          "maxLength": 35
        }
      }
    },
    "E1EDK02": {
      "description": "Header reference. QUALF 001 = customer purchase order / RFQ reference",
      "type": "object",
      "additionalProperties": false,
      "required": [
        "QUALF",
        "BELNR"
      ],
      "properties": {
        "QUALF": {
          "type": "string",
          "pattern": "^[0-9]{3}$"
        },
        "BELNR": {
          "type": "string",
          "minLength": 1,
          "maxLength": 35
        },
        "DATUM": {
          "$ref": "#/$defs/SapDate"
        }
      }
    },
    "E1EDP01": {
      "description": "Item general data",
      "type": "object",
      "additionalProperties": false,
      "required": [
        "POSEX",
        "MENGE",
        "MENEE",
        "E1EDP19"
      ],
      "properties": {
        "POSEX": {
          "description": "Item number",
          "type": "string",
          "pattern": "^[0-9]{1,6}$"
        },
        "MENGE": {
          "$ref": "#/$defs/SapQuantity"
        },
        "MENEE": {
          "$ref": "#/$defs/IsoUnit"
        },
        "E1EDP19": {
          "type": "array",
          "minItems": 1,
          "items": {
            "$ref": "#/$defs/E1EDP19"
          }
        },
        "E1EDP05": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/E1EDP05"
          }
        },
        "E1EDP20": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/E1EDP20"
          }
        }
      }
    },
    "E1EDP19": {
      "description": "Item object identification. 002 = material number (MATNR) of the selling company, 001 = customer material number",
      "type": "object",
      "additionalProperties": false,
      "required": [
        "QUALF",
        "IDTNR"
      ],
      "properties": {
        "QUALF": {
          "enum": [
            "001",
            "002"
          ]
        },
        "IDTNR": {
          "type": "string",
          "minLength": 1,
          "maxLength": 35
        },
        "KTEXT": {
          "description": "Short text",
          "type": "string",
          "maxLength": 70
        }
      }
    },
    "E1EDP05": {
      "description": "Item condition, e.g. PR00 price or a surcharge (Zuschlag) condition type",
      "type": "object",
      "additionalProperties": false,
      "required": [
        "KSCHL"
      ],
      "properties": {
        "ALCKZ": {
          "description": "+ surcharge, - discount",
          "enum": [
            "+",
            "-"
          ]
        },
        "KSCHL": {
          "type": "string",
          "minLength": 1,
          "maxLength": 4
        },
        "BETRG": {
          "$ref": "#/$defs/SapAmount"
        },
        "KRATE": {
          "$ref": "#/$defs/SapAmount"
        },
        "KPERC": {
          "description": "Percentage",
          "type": "string",
          "pattern": "^-?[0-9]{1,3}(\\.[0-9]{1,3})?$"
        }
      }
    },
    "E1EDP20": {
      "description": "Item schedule line",
      "type": "object",
      "additionalProperties": false,
      "required": [
        "WMENG"
      ],
      "properties": {
        "WMENG": {
          "$ref": "#/$defs/SapQuantity"
        },
        "EDATU": {
          "$ref": "#/$defs/SapDate"
        }
      }
    }
  }
} as const;

export default schema;
