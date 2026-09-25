"""Tests for the OpenWA config and options flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.openwa.const import (
    CONF_DEFAULT_CHAT_IDS,
    CONF_SCAN_INTERVAL,
    CONF_SESSIONS,
    CONF_WEBHOOK_URL,
    DOMAIN,
)

from .conftest import HA_URL
from .const import API_KEY, SESSION_ID, SESSION_NAME, SESSION_READY, URL, WEBHOOK_ID

BASE = f"{URL}/api/sessions/{SESSION_ID}"


def _mock_login(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(
        f"{URL}/api/auth/validate", json={"valid": True, "role": "operator"}
    )
    aioclient_mock.get(f"{URL}/api/sessions", json=[SESSION_READY])


async def _to_webhook_step(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL + "/", CONF_API_KEY: API_KEY}
    )
    assert result["step_id"] == "sessions"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SESSIONS: [SESSION_ID]}
    )
    assert result["step_id"] == "webhook"
    return result


async def test_full_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass.config.external_url = HA_URL
    _mock_login(aioclient_mock)
    aioclient_mock.post(f"{BASE}/webhooks", status=201, json={"id": WEBHOOK_ID})
    aioclient_mock.post(
        f"{BASE}/webhooks/{WEBHOOK_ID}/test", json={"success": True, "statusCode": 200}
    )

    result = await _to_webhook_step(hass)
    schema_default = result["data_schema"].schema
    assert any(
        getattr(k, "default", None) and k.default() == HA_URL for k in schema_default
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WEBHOOK_URL: HA_URL + "/"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_URL] == URL
    assert data[CONF_SESSIONS] == {SESSION_ID: SESSION_NAME}
    assert data[CONF_WEBHOOK_URL] == HA_URL
    assert len(data["webhook_secret"]) == 64

    create = next(
        c for c in aioclient_mock.mock_calls if str(c[1]) == f"{BASE}/webhooks"
    )
    body = create[2]
    assert body["url"] == f"{HA_URL}/api/webhook/{data['webhook_id']}"
    assert body["secret"] == data["webhook_secret"]
    assert "message.received" in body["events"]


async def test_invalid_auth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(
        f"{URL}/api/auth/validate", status=401, json={"message": "Invalid API key"}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_API_KEY: "bad"}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{URL}/api/auth/validate", exc=TimeoutError())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_API_KEY: API_KEY}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_no_sessions(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(
        f"{URL}/api/auth/validate", json={"valid": True, "role": "operator"}
    )
    aioclient_mock.get(f"{URL}/api/sessions", json=[])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_API_KEY: API_KEY}
    )
    assert result["errors"] == {"base": "no_sessions"}


async def test_webhook_test_failure_rolls_back(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    _mock_login(aioclient_mock)
    aioclient_mock.post(f"{BASE}/webhooks", status=201, json={"id": WEBHOOK_ID})
    aioclient_mock.post(
        f"{BASE}/webhooks/{WEBHOOK_ID}/test",
        json={"success": False, "error": "Blocked private address"},
    )
    aioclient_mock.delete(f"{BASE}/webhooks/{WEBHOOK_ID}", status=204)

    result = await _to_webhook_step(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WEBHOOK_URL: "http://10.0.0.5:8123"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "webhook_test_failed"}
    assert "Blocked private address" in result["description_placeholders"]["error"]
    assert any(c[0].upper() == "DELETE" for c in aioclient_mock.mock_calls)


async def test_already_configured(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL + "/", CONF_API_KEY: API_KEY}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    entry.add_to_hass(hass)
    aioclient_mock.post(
        f"{URL}/api/auth/validate", json={"valid": True, "role": "operator"}
    )
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new-key"


async def test_options_normalize_chat(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"default_chat": "+49 151 000-00002", CONF_SCAN_INTERVAL: 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.options[CONF_DEFAULT_CHAT_IDS] == {
        SESSION_ID: "4915100000002@c.us"
    }


async def test_options_reject_bad_chat(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"default_chat": "nope", CONF_SCAN_INTERVAL: 60}
    )
    assert result["errors"] == {"default_chat": "invalid_chat_id"}


async def test_options_national_number_uses_country(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    hass.config.country = "DE"
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"default_chat": "0151 00000002", CONF_SCAN_INTERVAL: 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.options[CONF_DEFAULT_CHAT_IDS] == {
        SESSION_ID: "4915100000002@c.us"
    }


async def test_options_own_messages_mode(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60, "own_messages": "self"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.options["own_messages"] == "self"


async def test_options_reject_own_number(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    # SESSION_READY's phone: sending notify there reaches nobody.
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"default_chat": "+49 151 00000000", CONF_SCAN_INTERVAL: 60}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"default_chat": "own_number"}


async def test_options_several_sessions_keyed_by_name(hass: HomeAssistant) -> None:
    second = "99999999-2222-4333-8444-555555555555"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_URL: URL,
            CONF_API_KEY: API_KEY,
            CONF_SESSIONS: {SESSION_ID: SESSION_NAME, second: "office"},
            "webhook_id": "x",
            "webhook_secret": "s" * 64,
            CONF_WEBHOOK_URL: HA_URL,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    keys = {str(k) for k in result["data_schema"].schema}
    assert {SESSION_NAME, "office"} <= keys
    assert "default_chat" not in keys
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"office": "+49 151 00000005", CONF_SCAN_INTERVAL: 60},
    )
    assert entry.options[CONF_DEFAULT_CHAT_IDS] == {second: "4915100000005@c.us"}
