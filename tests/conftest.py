"""Fixtures for OpenWA tests."""

from __future__ import annotations

import pytest
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.openwa.const import (
    CONF_DEFAULT_CHAT_IDS,
    CONF_SESSIONS,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    CONF_WEBHOOK_URL,
    DOMAIN,
)

from .const import API_KEY, SESSION_ID, SESSION_NAME, SESSION_READY, URL, WEBHOOK_ID

HA_URL = "https://ha.example.test"
HOOK_ID = "abc123hook"
SECRET = "s" * 64
CHAT = "4915100000001@c.us"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


@pytest.fixture
def entry() -> MockConfigEntry:
    """A configured entry with one session."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="openwa.test:2785",
        unique_id=URL,
        data={
            CONF_URL: URL,
            CONF_API_KEY: API_KEY,
            CONF_SESSIONS: {SESSION_ID: SESSION_NAME},
            CONF_WEBHOOK_ID: HOOK_ID,
            CONF_WEBHOOK_SECRET: SECRET,
            CONF_WEBHOOK_URL: HA_URL,
        },
        options={CONF_DEFAULT_CHAT_IDS: {SESSION_ID: CHAT}},
    )


def mock_server(
    aioclient_mock: AiohttpClientMocker,
    *,
    session: dict | None = None,
    webhooks: list | None = None,
    chats_exc: Exception | None = None,
    chats_status: int = 200,
) -> None:
    """Register the endpoints setup needs."""
    base = f"{URL}/api/sessions/{SESSION_ID}"
    aioclient_mock.post(
        f"{URL}/api/auth/validate", json={"valid": True, "role": "operator"}
    )
    aioclient_mock.get(f"{URL}/api/health", json={"status": "ok", "version": "0.23.6"})
    aioclient_mock.get(base, json=session or SESSION_READY)
    aioclient_mock.get(f"{base}/webhooks", json=webhooks or [])
    aioclient_mock.get(f"{base}/chats", json=[], exc=chats_exc, status=chats_status)
    aioclient_mock.post(f"{base}/webhooks", status=201, json={"id": WEBHOOK_ID})
    aioclient_mock.put(f"{base}/webhooks/{WEBHOOK_ID}", json={"id": WEBHOOK_ID})
    aioclient_mock.delete(f"{base}/webhooks/{WEBHOOK_ID}", status=204)


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> MockConfigEntry:
    """Set up the integration against a mocked server."""
    hass.config.external_url = HA_URL
    mock_server(aioclient_mock)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
