"""Session status sensor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SESSION_STATUSES
from .coordinator import OpenWAConfigEntry
from .entity import OpenWAEntity

PARALLEL_UPDATES = 0

ATTRIBUTES = ("phone", "pushName", "connectedAt", "lastError", "engineLoaded")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenWAConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up status sensors."""
    async_add_entities(
        OpenWAStatusSensor(c, "status")
        for c in entry.runtime_data.coordinators.values()
    )


class OpenWAStatusSensor(OpenWAEntity, SensorEntity):
    """Session status as enum."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = SESSION_STATUSES

    @property
    def native_value(self) -> str | None:
        """Return the status, None if OpenWA reports an unknown value."""
        return self.status if self.status in SESSION_STATUSES else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the session details from the API."""
        data = self.coordinator.data or {}
        return {key: data.get(key) for key in ATTRIBUTES}
