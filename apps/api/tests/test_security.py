from __future__ import annotations

import re

from zuschlag_api.core.security import pseudonymize_ip

KEY = b"k" * 32


def test_ip_hash_is_hex_sha256() -> None:
    digest = pseudonymize_ip("203.0.113.7", KEY)
    assert digest is not None
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_ipv6_spellings_normalise_to_same_pseudonym() -> None:
    assert pseudonymize_ip("2001:db8::1", KEY) == pseudonymize_ip("2001:0DB8:0:0:0:0:0:1", KEY)


def test_pseudonym_depends_on_key() -> None:
    assert pseudonymize_ip("203.0.113.7", KEY) != pseudonymize_ip("203.0.113.7", b"x" * 32)


def test_missing_ip() -> None:
    assert pseudonymize_ip(None, KEY) is None
