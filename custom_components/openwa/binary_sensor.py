"""Session connected binary sensor."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import STATUS_READY
from .coordinator import ENGINE_RESPONSIVE_KEY, OpenWAConfigEntry
from .entity import OpenWAEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenWAConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up connectivity sensors."""
    async_add_entities(
        OpenWAConnectedSensor(c, "connected")
        for c in entry.runtime_data.coordinators.values()
    )


class OpenWAConnectedSensor(OpenWAEntity, BinarySensorEntity):
    """On when the session status is ready."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool:
        """Return True if WhatsApp is connected and the engine answers."""
        return (
            self.status == STATUS_READY
            and (self.coordinator.data or {}).get(ENGINE_RESPONSIVE_KEY) is not False
        )
