"""SAP payment terms (ZTERM) for quotations.

Keys of the form ``NT<days>`` (e.g. NT30 = "net 30 days") are understood
directly. Any other key (SAP standard keys like 0001, customer-specific Z...)
must be declared in ``PAYMENT_TERMS_CATALOG`` with its net days, so no quote
ever goes out with terms nobody can explain.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_NET = re.compile(r"^NT(\d{1,3})$")


class PaymentTermsError(ValueError):
    """Unknown payment terms, or terms that contradict the customer's agreement."""


@dataclass(frozen=True, slots=True)
class PaymentTerms:
    zterm: str
    net_days: int

    @property
    def description_de(self) -> str:
        return "sofort zahlbar ohne Abzug" if self.net_days == 0 else f"{self.net_days} Tage netto"

    @property
    def description_en(self) -> str:
        return "due immediately, no discount" if self.net_days == 0 else f"net {self.net_days} days"


def parse_payment_terms(zterm: str, catalog: Mapping[str, int] | None = None) -> PaymentTerms:
    key = zterm.strip().upper()
    if not key or len(key) > 4:
        raise PaymentTermsError(f"invalid payment terms key {zterm!r} (ZTERM is 1-4 characters)")
    match = _NET.match(key)
    if match:
        return PaymentTerms(key, int(match.group(1)))
    if catalog and key in catalog:
        return PaymentTerms(key, int(catalog[key]))
    raise PaymentTermsError(
        f"unknown payment terms {key!r}: use NT<days> or declare the key in PAYMENT_TERMS_CATALOG"
    )


@dataclass(frozen=True, slots=True)
class TermsDecision:
    terms: PaymentTerms
    agreed: tuple[str, ...]  # the customer's ZTERMs from SAP (KNVV), if any
    deviation: bool  # true when the quote uses terms the customer has not agreed


def resolve_payment_terms(
    requested: str | None,
    *,
    agreed: Sequence[str],
    default: str,
    catalog: Mapping[str, int] | None = None,
    allow_deviation: bool = False,
) -> TermsDecision:
    """Pick and validate the ZTERM for a quote.

    * No request: the customer's agreed terms (first sales area), else `default`.
    * A request must be a known key and, when the customer has agreed terms in
      SAP, one of them, unless `allow_deviation` is set explicitly.
    """
    agreed_keys = tuple(dict.fromkeys(a.strip().upper() for a in agreed if a and a.strip()))
    chosen = (requested or (agreed_keys[0] if agreed_keys else default)).strip().upper()
    terms = parse_payment_terms(chosen, catalog)
    deviation = bool(agreed_keys) and terms.zterm not in agreed_keys
    if deviation and not allow_deviation:
        raise PaymentTermsError(
            f"payment terms {terms.zterm} deviate from the customer's agreed terms "
            f"{', '.join(agreed_keys)} (set allow_terms_deviation to override)"
        )
    return TermsDecision(terms, agreed_keys, deviation)
