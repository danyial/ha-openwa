"""Small pure helpers for the OpenWA integration."""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections import OrderedDict

_NON_DIGITS = re.compile(r"\D")
# "+49 (0) 151 …": the bracketed trunk zero must not end up in the number.
_TRUNK_ZERO = re.compile(r"\(\s*0\s*\)")

# ITU calling codes for countries whose national numbers start with a trunk
# "0". Countries without a trunk prefix (US, CA, …) don't need an entry:
# their numbers are dialled the same way nationally and internationally.
CALLING_CODES: dict[str, str] = {
    "AT": "43",
    "AU": "61",
    "BE": "32",
    "BG": "359",
    "CH": "41",
    "CZ": "420",
    "DE": "49",
    "DK": "45",
    "EE": "372",
    "ES": "34",
    "FI": "358",
    "FR": "33",
    "GB": "44",
    "GR": "30",
    "HR": "385",
    "HU": "36",
    "IE": "353",
    "IL": "972",
    "IN": "91",
    "IT": "39",
    "JP": "81",
    "LI": "423",
    "LT": "370",
    "LU": "352",
    "LV": "371",
    "NL": "31",
    "NO": "47",
    "NZ": "64",
    "PL": "48",
    "PT": "351",
    "RO": "40",
    "RS": "381",
    "SE": "46",
    "SI": "386",
    "SK": "421",
    "TR": "90",
    "UA": "380",
    "ZA": "27",
}
# Italy keeps the leading 0 of landline numbers in international format
# (06 … -> +39 06 …).
KEEP_LEADING_ZERO = frozenset({"IT"})


def normalize_chat_id(value: str, country: str | None = None) -> str:
    """Turn a phone number into '<digits>@c.us'; keep ids that have a suffix.

    '+49 151 234' and '0049 151 234' are international. A leading single '0'
    is a national number and gets the calling code of `country` (the HA
    country setting), e.g. '0151 234' with DE -> '49151234@c.us'.
    """
    value = value.strip()
    if "@" in value:
        return value
    international = value.startswith("+")
    digits = _NON_DIGITS.sub("", _TRUNK_ZERO.sub("", value))
    if not digits:
        raise ValueError(f"invalid chat id: {value!r}")
    if not international:
        if digits.startswith("00"):
            digits = digits[2:]
        elif digits.startswith("0"):
            country = (country or "").upper()
            code = CALLING_CODES.get(country)
            if code is None:
                raise ValueError(
                    f"national number {value!r} needs a country code; "
                    "use +<country code> or set the Home Assistant country"
                )
            digits = code + (digits if country in KEEP_LEADING_ZERO else digits[1:])
    if not digits or digits.startswith("0"):
        raise ValueError(f"invalid chat id: {value!r}")
    return f"{digits}@c.us"


def phone_chat_id(digits: object) -> str | None:
    """Map OpenWA's senderPhone (digits or null) to '<digits>@c.us'."""
    if not isinstance(digits, str):
        return None
    digits = _NON_DIGITS.sub("", digits)
    return f"{digits}@c.us" if digits else None


def signature_valid(secret: str, body: bytes, header: str | None) -> bool:
    """Check X-OpenWA-Signature: 'sha256=' + hex HMAC-SHA256 of the raw body."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)


class Deduplicator:
    """Remember recently seen keys for a limited time and count."""

    def __init__(self, max_size: int = 1000, ttl: float = 600) -> None:
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl

    def seen(self, key: str) -> bool:
        """Return True if key was seen before; otherwise remember it."""
        now = time.monotonic()
        while self._seen:
            oldest_key, stamp = next(iter(self._seen.items()))
            if now - stamp < self._ttl and len(self._seen) < self._max_size:
                break
            del self._seen[oldest_key]
        if key in self._seen:
            return True
        self._seen[key] = now
        return False
