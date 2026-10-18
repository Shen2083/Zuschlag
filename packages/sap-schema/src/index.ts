import { Ajv2020, type ErrorObject, type ValidateFunction } from "ajv/dist/2020.js";

import orders05QuotationSchema from "./generated/orders05-quotation.schema.js";
import type { Orders05Quotation } from "./generated/orders05-quotation.js";

export type * from "./generated/orders05-quotation.js";
export { orders05QuotationSchema };

const ajv = new Ajv2020({ allErrors: true, strict: true });
const validateOrders05: ValidateFunction<Orders05Quotation> =
  ajv.compile<Orders05Quotation>(orders05QuotationSchema);

export interface ValidationResult<T> {
  ok: boolean;
  value?: T;
  errors: ErrorObject[];
}

/** Validate an ORDERS05 quotation IDoc against the shared JSON Schema. */
export function validateOrders05Quotation(data: unknown): ValidationResult<Orders05Quotation> {
  if (validateOrders05(data)) {
    return { ok: true, value: data, errors: [] };
  }
  return { ok: false, errors: [...(validateOrders05.errors ?? [])] };
}
