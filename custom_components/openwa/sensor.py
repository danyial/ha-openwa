"""Session status sensor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SESSION_STATUSES, STATUS_READY, STATUS_UNRESPONSIVE
from .coordinator import ENGINE_RESPONSIVE_KEY, OpenWAConfigEntry
from .entity import OpenWAEntity

PARALLEL_UPDATES = 0

ATTRIBUTES = ("phone", "pushName", "connectedAt", "lastError", "engineLoaded")
OPTIONS = [*SESSION_STATUSES, STATUS_UNRESPONSIVE]


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
    _attr_options = OPTIONS

    @property
    def native_value(self) -> str | None:
        """Return the status, None if OpenWA reports an unknown value."""
        if (
            self.status == STATUS_READY
            and (self.coordinator.data or {}).get(ENGINE_RESPONSIVE_KEY) is False
        ):
            return STATUS_UNRESPONSIVE
        return self.status if self.status in SESSION_STATUSES else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the session details from the API."""
        data = self.coordinator.data or {}
        return {
            **{key: data.get(key) for key in ATTRIBUTES},
            ENGINE_RESPONSIVE_KEY: data.get(ENGINE_RESPONSIVE_KEY),
        }
