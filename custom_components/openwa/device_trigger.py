"""Device trigger for incoming WhatsApp messages."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, EVENT_OPENWA
from .helpers import normalize_chat_id

TRIGGER_MESSAGE_RECEIVED = "message_received"
CONF_FROM = "from"

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In([TRIGGER_MESSAGE_RECEIVED]),
        vol.Optional(CONF_FROM): cv.string,
    }
)


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """List triggers for an OpenWA session device."""
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: TRIGGER_MESSAGE_RECEIVED,
        }
    ]


async def async_get_trigger_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, vol.Schema]:
    """Offer an optional sender filter."""
    return {"extra_fields": vol.Schema({vol.Optional(CONF_FROM): str})}


async def async_validate_trigger_config(
    hass: HomeAssistant, config: ConfigType
) -> ConfigType:
    """Normalize the sender filter; national numbers use the HA country."""
    config = TRIGGER_SCHEMA(config)
    if sender := config.get(CONF_FROM):
        try:
            config[CONF_FROM] = normalize_chat_id(sender, hass.config.country)
        except ValueError as err:
            raise vol.Invalid(str(err)) from err
    return config


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Listen for openwa_event message.received on this device.

    With a sender filter, match it against `from` or `sender_phone`: senders
    hidden behind a WhatsApp LID carry the LID in `from` and the resolved
    number (if OpenWA resolves it) in `sender_phone`. A message never matches
    both, since `sender_phone` is only set for LID senders.
    """
    base = {"event_type": "message.received", "device_id": config[CONF_DEVICE_ID]}
    sender = config.get(CONF_FROM)
    filters = (
        [{**base, key: sender} for key in ("from", "sender_phone")]
        if sender
        else [base]
    )
    unsubs = [
        await event_trigger.async_attach_trigger(
            hass,
            event_trigger.TRIGGER_SCHEMA(
                {
                    event_trigger.CONF_PLATFORM: "event",
                    event_trigger.CONF_EVENT_TYPE: EVENT_OPENWA,
                    event_trigger.CONF_EVENT_DATA: event_data,
                }
            ),
            action,
            trigger_info,
            platform_type="device",
        )
        for event_data in filters
    ]

    @callback
    def _unsubscribe() -> None:
        for unsub in unsubs:
            unsub()

    return _unsubscribe
