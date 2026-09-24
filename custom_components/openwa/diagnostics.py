"""Diagnostics for OpenWA."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .const import CONF_WEBHOOK_ID, CONF_WEBHOOK_SECRET
from .coordinator import OpenWAConfigEntry

TO_REDACT = {CONF_API_KEY, CONF_WEBHOOK_ID, CONF_WEBHOOK_SECRET, "phone", "qr"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OpenWAConfigEntry
) -> dict[str, Any]:
    """Return redacted entry data and session states."""
    data = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "server_version": data.version,
        "sessions": {
            sid: async_redact_data(dict(c.data or {}), TO_REDACT)
            for sid, c in data.coordinators.items()
        },
    }
