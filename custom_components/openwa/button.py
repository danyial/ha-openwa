"""Session lifecycle buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import OpenWAError
from .coordinator import OpenWAConfigEntry, OpenWASessionCoordinator
from .entity import OpenWAEntity

PARALLEL_UPDATES = 1

ACTIONS = ("start", "stop", "logout")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenWAConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up start/stop/logout buttons."""
    async_add_entities(
        OpenWAButton(c, action)
        for c in entry.runtime_data.coordinators.values()
        for action in ACTIONS
    )


class OpenWAButton(OpenWAEntity, ButtonEntity):
    """Trigger a session lifecycle action."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: OpenWASessionCoordinator, action: str) -> None:
        """Initialize the button."""
        super().__init__(coordinator, action)
        self._action = action

    async def async_press(self) -> None:
        """Run the action, then refresh the status."""
        try:
            await self.coordinator.client.session_action(
                self.coordinator.session_id, self._action
            )
        except OpenWAError as err:
            raise HomeAssistantError(f"OpenWA {self._action} failed: {err}") from err
        await self.coordinator.async_request_refresh()
