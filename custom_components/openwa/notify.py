"""Notify entity per session, sending to the configured default chat."""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import OpenWAError, RateLimited
from .const import CONF_DEFAULT_CHAT_IDS
from .coordinator import OpenWAConfigEntry
from .entity import OpenWAEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenWAConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up notify entities."""
    async_add_entities(
        OpenWANotify(c, "notify") for c in entry.runtime_data.coordinators.values()
    )


def format_message(message: str, title: str | None) -> str:
    """Prefix the title in WhatsApp bold."""
    return f"*{title}*\n{message}" if title else message


class OpenWANotify(OpenWAEntity, NotifyEntity):
    """Send a text to the session's default chat."""

    _attr_name = None  # use the device name

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a message."""
        chats = self.coordinator.config_entry.options.get(CONF_DEFAULT_CHAT_IDS, {})
        chat_id = chats.get(self.coordinator.session_id)
        if not chat_id:
            raise ServiceValidationError(
                f"No default chat configured for {self.coordinator.session_name}; "
                "set one in the integration options or use openwa.send_message"
            )
        try:
            await self.coordinator.client.send_text(
                self.coordinator.session_id, chat_id, format_message(message, title)
            )
        except RateLimited as err:
            raise HomeAssistantError(
                f"OpenWA rate limit, retry after {err.retry_after or '?'} s"
            ) from err
        except OpenWAError as err:
            raise HomeAssistantError(f"Sending failed: {err}") from err
