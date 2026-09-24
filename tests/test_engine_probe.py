"""Tests for detecting a hung engine behind a "ready" session."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .conftest import mock_server
from .const import SESSION_ID

SENSOR = "sensor.home_assistant_status"
CONNECTED = "binary_sensor.home_assistant_connected"


async def _refresh(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    **server: object,
) -> None:
    aioclient_mock.clear_requests()
    mock_server(aioclient_mock, **server)
    await entry.runtime_data.coordinators[SESSION_ID].async_refresh()
    await hass.async_block_till_done()


async def test_ready_engine_is_responsive(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    assert hass.states.get(SENSOR).state == "ready"
    assert hass.states.get(SENSOR).attributes["engine_responsive"] is True
    assert hass.states.get(CONNECTED).state == "on"


async def test_two_timeouts_mark_unresponsive_then_recover(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    await _refresh(hass, setup_entry, aioclient_mock, chats_exc=TimeoutError())
    # One slow answer is tolerated.
    assert hass.states.get(SENSOR).state == "ready"
    assert hass.states.get(CONNECTED).state == "on"

    await _refresh(hass, setup_entry, aioclient_mock, chats_exc=TimeoutError())
    state = hass.states.get(SENSOR)
    assert state.state == "unresponsive"
    assert state.attributes["engine_responsive"] is False
    assert hass.states.get(CONNECTED).state == "off"

    await _refresh(hass, setup_entry, aioclient_mock)
    assert hass.states.get(SENSOR).state == "ready"
    assert hass.states.get(CONNECTED).state == "on"


async def test_success_resets_failure_count(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    await _refresh(hass, setup_entry, aioclient_mock, chats_exc=TimeoutError())
    await _refresh(hass, setup_entry, aioclient_mock)
    await _refresh(hass, setup_entry, aioclient_mock, chats_exc=TimeoutError())
    assert hass.states.get(SENSOR).state == "ready"


async def test_error_answer_counts_as_responsive(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    for _ in range(3):
        await _refresh(hass, setup_entry, aioclient_mock, chats_status=500)
    assert hass.states.get(SENSOR).state == "ready"


async def test_not_ready_is_not_probed(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    await _refresh(
        hass,
        setup_entry,
        aioclient_mock,
        session={"id": SESSION_ID, "status": "disconnected"},
    )
    assert not any(c[1].path.endswith("/chats") for c in aioclient_mock.mock_calls)
    state = hass.states.get(SENSOR)
    assert state.state == "disconnected"
    assert state.attributes["engine_responsive"] is None
