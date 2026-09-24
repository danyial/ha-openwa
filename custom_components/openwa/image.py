"""QR code image for pairing."""

from __future__ import annotations

import base64
import binascii

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import STATUS_QR_READY
from .coordinator import QR_KEY, OpenWAConfigEntry, OpenWASessionCoordinator
from .entity import OpenWAEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenWAConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up QR images."""
    async_add_entities(
        OpenWAQrImage(hass, c) for c in entry.runtime_data.coordinators.values()
    )


def decode_data_url(value: str | None) -> bytes | None:
    """Decode 'data:image/png;base64,...' to bytes."""
    if not value or "," not in value:
        return None
    try:
        return base64.b64decode(value.split(",", 1)[1], validate=True)
    except binascii.Error, ValueError:
        return None


class OpenWAQrImage(OpenWAEntity, ImageEntity):
    """Pairing QR, available only while the session waits for a scan."""

    _attr_content_type = "image/png"

    def __init__(
        self, hass: HomeAssistant, coordinator: OpenWASessionCoordinator
    ) -> None:
        """Initialize the image."""
        OpenWAEntity.__init__(self, coordinator, "qr")
        ImageEntity.__init__(self, hass)
        self._qr: str | None = None
        self._update_qr()

    @property
    def available(self) -> bool:
        """Only available with a QR to show."""
        return (
            super().available
            and self.status == STATUS_QR_READY
            and self._qr is not None
        )

    @callback
    def _update_qr(self) -> None:
        qr = (self.coordinator.data or {}).get(QR_KEY)
        if qr != self._qr:
            self._qr = qr
            self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_qr()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return the PNG bytes."""
        return decode_data_url(self._qr)
