"""The structured output the LLM must produce for an inbound RFQ.

This schema is sent to the model as a JSON Schema (structured outputs), so it
follows the API's constraints: no recursion, and numeric bounds are enforced
client-side by Pydantic rather than by the model. Enums keep units, item kinds
and fabrication operations to a closed vocabulary the rest of the pipeline
understands.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ISO / UN-ECE Rec. 20 unit codes as used in SAP (T006-ISOCODE).
UnitCode = Literal["PCE", "SET", "PR", "KGM", "TNE", "MTR", "MTK", "MTQ", "LTR", "HUR", "ROL"]
UNIT_LABELS: dict[str, str] = {
    "PCE": "piece / Stück",
    "SET": "set / Satz",
    "PR": "pair / Paar",
    "KGM": "kilogram",
    "TNE": "tonne",
    "MTR": "metre",
    "MTK": "square metre",
    "MTQ": "cubic metre",
    "LTR": "litre",
    "HUR": "hour",
    "ROL": "roll",
}

ItemKind = Literal["finished_good", "semi_finished", "raw_material", "purchased_part", "service"]
ComponentKind = Literal["raw_material", "semi_finished", "purchased_part"]
Operation = Literal[
    "cutting",
    "bending",
    "welding",
    "machining",
    "assembly",
    "surface_treatment",
    "quality_inspection",
]
SpecConstraint = Literal["exact", "min", "max", "approx"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TechnicalSpec(_Model):
    """One requirement, e.g. load capacity >= 250 kg, material 1.4301."""

    name: str = Field(description="Requirement name as in the inquiry, e.g. 'Belastbarkeit'")
    value: str = Field(description="Value, e.g. '250' or '1.4301' or 'IP54'")
    unit: str | None = Field(default=None, description="Unit of the value, e.g. 'kg', 'mm'")
    constraint: SpecConstraint = Field(
        default="exact", description="'min' for mindestens/at least, 'max' for höchstens/max."
    )


class CustomerInfo(_Model):
    company_name: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    customer_reference: str | None = Field(
        default=None, description="The customer's own inquiry or order reference, if stated"
    )
    target_delivery_date: date | None = Field(
        default=None, description="Requested delivery date, resolved to a calendar date"
    )
    delivery_date_text: str | None = Field(
        default=None, description="The delivery wording verbatim, e.g. 'bis KW 48'"
    )


class BomComponent(_Model):
    description: str = Field(description="Component, e.g. 'Edelstahlblech 1.4301, 2 mm'")
    search_text: str = Field(
        description="Catalog search phrase in German and English with grade and key dimensions"
    )
    kind: ComponentKind
    quantity_per_unit: float = Field(gt=0, description="Quantity for ONE finished unit")
    unit: UnitCode
    specs: list[TechnicalSpec] = Field(default_factory=list)


class LaborOperation(_Model):
    operation: Operation
    hours_per_unit: float = Field(gt=0, description="Estimated shop hours for ONE finished unit")
    note: str | None = None


class LineItem(_Model):
    position: int = Field(ge=1, description="1-based position in the order of the inquiry")
    description: str = Field(description="Requested part, close to the customer's wording")
    search_text: str = Field(
        description="Catalog search phrase in German and English with grade and key dimensions"
    )
    quantity: float = Field(gt=0)
    unit: UnitCode
    kind: ItemKind
    is_custom_made: bool = Field(
        description="True for made-to-order goods (nach Maß, Sonderanfertigung, custom)"
    )
    material_number: str | None = Field(
        default=None, description="SAP material / article number if the inquiry cites one"
    )
    specs: list[TechnicalSpec] = Field(default_factory=list)
    components: list[BomComponent] = Field(
        default_factory=list, description="Proposed BOM, only for custom-made finished goods"
    )
    labor: list[LaborOperation] = Field(
        default_factory=list, description="Fabrication operations, only for custom-made goods"
    )


class RfqExtraction(_Model):
    language: Literal["de", "en", "other"]
    summary: str = Field(description="One sentence: what the customer wants")
    customer: CustomerInfo
    line_items: list[LineItem] = Field(min_length=1)
    open_questions: list[str] = Field(
        default_factory=list, description="Information a sales engineer must still clarify"
    )
