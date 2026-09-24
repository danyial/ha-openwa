"""Base entity for OpenWA sessions."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OpenWASessionCoordinator


class OpenWAEntity(CoordinatorEntity[OpenWASessionCoordinator]):
    """One entity of one OpenWA session (= device)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OpenWASessionCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.session_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.session_id)},
            name=coordinator.session_name,
            manufacturer="OpenWA",
            model="WhatsApp session",
            sw_version=coordinator.config_entry.runtime_data.version,
            configuration_url=coordinator.client.base_url,
        )

    @property
    def status(self) -> str | None:
        """Return the current session status."""
        return (self.coordinator.data or {}).get("status")
