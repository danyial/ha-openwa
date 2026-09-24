"""Tests for pure helpers."""

from __future__ import annotations

import pytest

from custom_components.openwa.helpers import normalize_chat_id, phone_chat_id


@pytest.mark.parametrize(
    ("value", "country", "expected"),
    [
        ("+49 174 4445455", None, "491744445455@c.us"),
        ("+49 (0) 174 4445455", None, "491744445455@c.us"),
        ("0049 174-4445455", None, "491744445455@c.us"),
        ("491744445455", None, "491744445455@c.us"),
        ("0174 4445455", "DE", "491744445455@c.us"),
        ("0174 4445455", "de", "491744445455@c.us"),
        ("0664 1234567", "AT", "436641234567@c.us"),
        ("06 1234 5678", "IT", "390612345678@c.us"),
        ("120363000000000000@g.us", None, "120363000000000000@g.us"),
        ("209569389236259@lid", "DE", "209569389236259@lid"),
    ],
)
def test_normalize_chat_id(value: str, country: str | None, expected: str) -> None:
    assert normalize_chat_id(value, country) == expected


@pytest.mark.parametrize(
    ("value", "country"),
    [
        ("0174 4445455", None),  # national without country
        ("0174 4445455", "US"),  # country without trunk prefix
        ("", "DE"),
        ("abc", "DE"),
        ("+0 174", None),
        ("00", None),
    ],
)
def test_normalize_chat_id_rejects(value: str, country: str | None) -> None:
    with pytest.raises(ValueError):
        normalize_chat_id(value, country)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("491744445455", "491744445455@c.us"),
        (None, None),
        ("", None),
        (491744445455, None),
    ],
)
def test_phone_chat_id(value: object, expected: str | None) -> None:
    assert phone_chat_id(value) == expected
