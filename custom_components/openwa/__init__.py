"""The OpenWA integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.const import CONF_API_KEY, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.json import json_loads

from .api import CannotConnect, InvalidAuth, OpenWAClient, OpenWAError
from .const import (
    CONF_INCLUDE_SENT,
    CONF_SCAN_INTERVAL,
    CONF_SESSIONS,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    CONF_WEBHOOK_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_OPENWA,
    SESSION_EVENTS,
    SUPPORTED_VERSION_PREFIX,
    webhook_events,
)
from .coordinator import OpenWAConfigEntry, OpenWAData, OpenWASessionCoordinator
from .helpers import phone_chat_id, signature_valid
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.NOTIFY,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide services."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OpenWAConfigEntry) -> bool:
    """Set up an OpenWA instance."""
    client = _client(hass, entry)
    try:
        await client.validate()
        version = await client.version()
    except InvalidAuth as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except OpenWAError as err:
        raise ConfigEntryNotReady(str(err)) from err

    if version and not version.startswith(SUPPORTED_VERSION_PREFIX):
        _LOGGER.warning(
            "OpenWA %s is untested; this integration targets %sx",
            version,
            SUPPORTED_VERSION_PREFIX,
        )

    interval = timedelta(
        seconds=entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds()
        )
    )
    coordinators = {
        sid: OpenWASessionCoordinator(hass, entry, client, sid, name, interval)
        for sid, name in entry.data[CONF_SESSIONS].items()
    }
    for coordinator in coordinators.values():
        await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = OpenWAData(client, version, coordinators)

    await _async_reconcile_webhooks(entry)
    webhook.async_register(
        hass,
        DOMAIN,
        f"OpenWA {entry.title}",
        entry.data[CONF_WEBHOOK_ID],
        _async_handle_webhook,
        allowed_methods=["POST"],
    )
    entry.async_on_unload(
        lambda: webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenWAConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: OpenWAConfigEntry) -> None:
    """Delete our webhooks on the OpenWA side."""
    client = _client(hass, entry)
    for sid in entry.data[CONF_SESSIONS]:
        try:
            for hook in await client.list_webhooks(sid):
                if _is_ours(entry, hook):
                    await client.delete_webhook(sid, hook["id"])
        except OpenWAError as err:
            _LOGGER.warning("Could not delete OpenWA webhook for %s: %s", sid, err)


async def _async_reload(hass: HomeAssistant, entry: OpenWAConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _client(hass: HomeAssistant, entry: OpenWAConfigEntry) -> OpenWAClient:
    return OpenWAClient(
        async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_API_KEY]
    )


def _target_url(entry: OpenWAConfigEntry) -> str:
    return entry.data[CONF_WEBHOOK_URL] + webhook.async_generate_path(
        entry.data[CONF_WEBHOOK_ID]
    )


def _is_ours(entry: OpenWAConfigEntry, hook: dict[str, Any]) -> bool:
    return str(hook.get("url", "")).endswith(
        webhook.async_generate_path(entry.data[CONF_WEBHOOK_ID])
    )


async def _async_reconcile_webhooks(entry: OpenWAConfigEntry) -> None:
    """Make sure each session has exactly one webhook to us with our secret."""
    client = entry.runtime_data.client
    target = _target_url(entry)
    secret = entry.data[CONF_WEBHOOK_SECRET]
    events = webhook_events(entry.options.get(CONF_INCLUDE_SENT, False))
    for sid in entry.runtime_data.coordinators:
        try:
            ours = [h for h in await client.list_webhooks(sid) if _is_ours(entry, h)]
            if not ours:
                _LOGGER.info("Re-creating OpenWA webhook for session %s", sid)
                await client.create_webhook(sid, target, events, secret)
                continue
            # PUT is idempotent and re-syncs the write-only secret.
            await client.update_webhook(sid, ours[0]["id"], target, events, secret)
            for extra in ours[1:]:
                await client.delete_webhook(sid, extra["id"])
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CannotConnect as err:
            raise ConfigEntryNotReady(str(err)) from err
        except OpenWAError as err:
            # Polling still works without push; don't block setup.
            _LOGGER.warning("Webhook sync for session %s failed: %s", sid, err)


async def _async_handle_webhook(
    hass: HomeAssistant, webhook_id: str, request: web.Request
) -> web.Response:
    """Verify, deduplicate and dispatch one OpenWA delivery."""
    entry = _entry_for_webhook(hass, webhook_id)
    if entry is None:
        return web.Response(status=HTTPStatus.NOT_FOUND)

    body = await request.read()
    if not signature_valid(
        entry.data[CONF_WEBHOOK_SECRET],
        body,
        request.headers.get("X-OpenWA-Signature"),
    ):
        _LOGGER.warning("Rejected OpenWA webhook with invalid signature")
        return web.Response(status=HTTPStatus.UNAUTHORIZED)

    try:
        payload = json_loads(body)
    except ValueError:
        return web.Response(status=HTTPStatus.BAD_REQUEST)
    if not isinstance(payload, dict):
        return web.Response(status=HTTPStatus.BAD_REQUEST)

    event = payload.get("event")
    session_id = payload.get("sessionId")
    data = payload.get("data") or {}
    coordinator = entry.runtime_data.coordinators.get(session_id)
    if event == "test" or coordinator is None:
        return web.Response(status=HTTPStatus.OK)

    key = payload.get("idempotencyKey") or request.headers.get(
        "X-OpenWA-Idempotency-Key"
    )
    if key and entry.runtime_data.dedupe.seen(key):
        return web.Response(status=HTTPStatus.OK)

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, session_id), entry.entry_id
    )
    event_data: dict[str, Any] = {
        "event_type": event,
        "session_id": session_id,
        "session_name": coordinator.session_name,
        "device_id": device.id if device else None,
        "timestamp": payload.get("timestamp"),
        "data": data,
    }
    if isinstance(data, dict) and event and event.startswith("message."):
        event_data["from"] = data.get("from")
        # Only set for @lid senders when OpenWA runs with RESOLVE_LID_TO_PHONE.
        event_data["sender_phone"] = phone_chat_id(data.get("senderPhone"))
    hass.bus.async_fire(EVENT_OPENWA, event_data)

    if event in SESSION_EVENTS and isinstance(data, dict):
        coordinator.async_handle_event(event, data)
    return web.Response(status=HTTPStatus.OK)


def _entry_for_webhook(
    hass: HomeAssistant, webhook_id: str
) -> OpenWAConfigEntry | None:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        if entry.data[CONF_WEBHOOK_ID] == webhook_id:
            return entry
    return None
