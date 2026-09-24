"""Small pure helpers for the OpenWA integration."""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections import OrderedDict

_NON_DIGITS = re.compile(r"\D")


def normalize_chat_id(value: str) -> str:
    """Turn '+49 151 234' into '49151234@c.us'; keep ids that have a suffix."""
    value = value.strip()
    if "@" in value:
        return value
    digits = _NON_DIGITS.sub("", value)
    if not digits:
        raise ValueError(f"invalid chat id: {value!r}")
    return f"{digits}@c.us"


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
