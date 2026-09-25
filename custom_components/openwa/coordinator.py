"""Per-session coordinator: polling fallback plus push updates from webhooks."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InvalidAuth, OpenWAClient, OpenWAError
from .const import DOMAIN, STATUS_QR_READY
from .helpers import Deduplicator

_LOGGER = logging.getLogger(__name__)

# Key in coordinator data holding the current QR data URL (not part of the API).
QR_KEY = "qr"


@dataclass
class OpenWAData:
    """Runtime data stored on the config entry."""

    client: OpenWAClient
    version: str | None
    coordinators: dict[str, OpenWASessionCoordinator]
    dedupe: Deduplicator = field(default_factory=Deduplicator)


type OpenWAConfigEntry = ConfigEntry[OpenWAData]


class OpenWASessionCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holds the SessionResponseDto of one session plus the current QR."""

    config_entry: OpenWAConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: OpenWAConfigEntry,
        client: OpenWAClient,
        session_id: str,
        session_name: str,
        interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {session_name}",
            update_interval=interval,
        )
        self.client = client
        self.session_id = session_id
        self.session_name = session_name
        # LID -> phone digits (or None); stable, so resolved once per LID.
        self._lid_phones: dict[str, str | None] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.client.get_session(self.session_id)
            qr = None
            if data.get("status") == STATUS_QR_READY:
                qr = await self.client.get_qr(self.session_id)
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except OpenWAError as err:
            raise UpdateFailed(str(err)) from err
        return {**data, QR_KEY: qr}

    async def async_is_to_self(self, data: dict[str, Any]) -> bool:
        """Return True for an own message written into the chat with yourself.

        The self chat is either '<own number>@c.us' or, with WhatsApp's
        linked IDs, the account's own '…@lid' while `from` stays the number.
        A LID is resolved through OpenWA and compared with the session phone.
        """
        to, sender = data.get("to"), data.get("from")
        if not data.get("fromMe") or not isinstance(to, str):
            return False
        if to == sender:
            return True
        own = _digits((self.data or {}).get("phone"))
        if not own:
            return False
        user, _, server = to.partition("@")
        if server == "c.us":
            return _digits(user) == own
        if server != "lid":
            return False
        if to not in self._lid_phones:
            try:
                phone = await self.client.resolve_contact_phone(self.session_id, to)
            except OpenWAError as err:
                _LOGGER.debug("Could not resolve %s: %s", to, err)
                return False
            self._lid_phones[to] = _digits(phone)
        return self._lid_phones[to] == own

    @callback
    def async_handle_event(self, event: str, data: dict[str, Any]) -> None:
        """Apply a session.* webhook event, then confirm via REST."""
        current = dict(self.data or {})
        match event:
            case "session.qr":
                current[QR_KEY] = data.get("qr")
                current["status"] = STATUS_QR_READY
            case "session.status":
                if status := data.get("status"):
                    current["status"] = status
                if current.get("status") != STATUS_QR_READY:
                    current[QR_KEY] = None
            case "session.authenticated":
                current["phone"] = data.get("phone")
                current["pushName"] = data.get("pushName")
                current[QR_KEY] = None
            case "session.disconnected":
                current["status"] = "disconnected"
                current["lastError"] = data.get("reason")
                current[QR_KEY] = None
            case _:
                return
        self.async_set_updated_data(current)
        # The QR itself only arrives via push; everything else gets re-read so
        # fields like connectedAt stay authoritative.
        if event != "session.qr":
            self.hass.async_create_task(self.async_request_refresh())


def _digits(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits or None
