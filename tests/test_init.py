"""Tests for setup, webhook handling, entities and services."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import pytest
import voluptuous as vol
from homeassistant.components import automation
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.openwa.const import DOMAIN, EVENT_OPENWA
from custom_components.openwa.device_trigger import (
    async_get_triggers,
    async_validate_trigger_config,
)

from .conftest import CHAT, HA_URL, HOOK_ID, SECRET, mock_server
from .const import QR_DATA_URL, SESSION_ID, SESSION_NAME, URL, WEBHOOK_ID

BASE = f"{URL}/api/sessions/{SESSION_ID}"
SENSOR = "sensor.home_assistant_status"
CONNECTED = "binary_sensor.home_assistant_connected"
QR = "image.home_assistant_pairing_qr_code"
NOTIFY = "notify.home_assistant"


def _delivery(event: str, data: dict[str, Any], key: str = "k1") -> dict:
    return {
        "event": event,
        "timestamp": "2026-09-24T10:00:00.000Z",
        "sessionId": SESSION_ID,
        "idempotencyKey": key,
        "deliveryId": "d1",
        "data": data,
    }


async def _post(
    client_factory: ClientSessionGenerator,
    payload: dict,
    *,
    secret: str = SECRET,
    signature: str | None = None,
) -> int:
    body = json.dumps(payload).encode()
    sig = signature or (
        "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    )
    client = await client_factory()
    resp = await client.post(
        f"/api/webhook/{HOOK_ID}",
        data=body,
        headers={"Content-Type": "application/json", "X-OpenWA-Signature": sig},
    )
    return resp.status


async def test_setup_creates_entities(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    assert setup_entry.state is ConfigEntryState.LOADED
    state = hass.states.get(SENSOR)
    assert state.state == "ready"
    assert state.attributes["pushName"] == "HA"
    assert hass.states.get(CONNECTED).state == "on"
    assert hass.states.get(QR).state == "unavailable"
    assert hass.states.get(NOTIFY) is not None
    assert hass.states.get("button.home_assistant_log_out") is not None

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, SESSION_ID), setup_entry.entry_id
    )
    assert device.name == SESSION_NAME
    assert device.sw_version == "0.23.6"


async def test_setup_creates_missing_webhook(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    create = [
        c
        for c in aioclient_mock.mock_calls
        if c[0].upper() == "POST" and str(c[1]) == f"{BASE}/webhooks"
    ]
    assert len(create) == 1
    assert create[0][2]["url"] == f"{HA_URL}/api/webhook/{HOOK_ID}"
    assert create[0][2]["secret"] == SECRET


async def test_setup_updates_existing_webhook(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_server(
        aioclient_mock,
        webhooks=[
            {"id": WEBHOOK_ID, "url": f"http://old/api/webhook/{HOOK_ID}"},
            {"id": "foreign", "url": "https://elsewhere/hook"},
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    methods = [(c[0].upper(), str(c[1])) for c in aioclient_mock.mock_calls]
    assert ("PUT", f"{BASE}/webhooks/{WEBHOOK_ID}") in methods
    assert ("POST", f"{BASE}/webhooks") not in methods
    assert not any("foreign" in url for _, url in methods)


async def test_setup_auth_failure_starts_reauth(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(
        f"{URL}/api/auth/validate", status=401, json={"message": "Invalid API key"}
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert flows[0]["context"]["source"] == "reauth"


async def test_setup_unreachable_retries(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{URL}/api/auth/validate", exc=TimeoutError())
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_message_received_fires_event(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    events = async_capture_events(hass, EVENT_OPENWA)
    message = {"id": "m1", "from": "4915100000009@c.us", "body": "hallo"}
    status = await _post(hass_client_no_auth, _delivery("message.received", message))
    await hass.async_block_till_done()

    assert status == 200
    assert len(events) == 1
    data = events[0].data
    assert data["event_type"] == "message.received"
    assert data["session_id"] == SESSION_ID
    assert data["session_name"] == SESSION_NAME
    assert data["from"] == "4915100000009@c.us"
    assert data["data"]["body"] == "hallo"
    assert data["device_id"] is not None


async def test_bad_signature_rejected(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    events = async_capture_events(hass, EVENT_OPENWA)
    payload = _delivery("message.received", {"from": "x", "body": "evil"})
    assert await _post(hass_client_no_auth, payload, secret="wrong" * 4) == 401
    assert await _post(hass_client_no_auth, payload, signature="garbage") == 401
    await hass.async_block_till_done()
    assert events == []


async def test_duplicate_delivery_fires_once(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    events = async_capture_events(hass, EVENT_OPENWA)
    payload = _delivery("message.received", {"from": "x", "body": "once"}, key="dup")
    assert await _post(hass_client_no_auth, payload) == 200
    assert await _post(hass_client_no_auth, payload) == 200
    await hass.async_block_till_done()
    assert len(events) == 1


async def test_test_event_is_ignored(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    events = async_capture_events(hass, EVENT_OPENWA)
    payload = {"event": "test", "sessionId": SESSION_ID, "data": {}}
    assert await _post(hass_client_no_auth, payload) == 200
    await hass.async_block_till_done()
    assert events == []


async def test_push_qr_then_ready(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    # Server now reports qr_ready so the follow-up refresh agrees.
    aioclient_mock.clear_requests()
    mock_server(aioclient_mock, session={"id": SESSION_ID, "status": "qr_ready"})
    aioclient_mock.get(f"{BASE}/qr", json={"qrCode": QR_DATA_URL})

    await _post(
        hass_client_no_auth,
        _delivery("session.qr", {"sessionId": SESSION_ID, "qr": QR_DATA_URL}, "q1"),
    )
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "qr_ready"
    assert hass.states.get(CONNECTED).state == "off"
    assert hass.states.get(QR).state != "unavailable"

    client = await hass_client_no_auth()
    token = hass.states.get(QR).attributes["access_token"]
    resp = await client.get(f"/api/image_proxy/{QR}?token={token}")
    assert resp.status == 200
    assert await resp.read() == base64.b64decode(QR_DATA_URL.split(",", 1)[1])

    aioclient_mock.clear_requests()
    mock_server(aioclient_mock)
    await _post(
        hass_client_no_auth,
        _delivery("session.status", {"sessionId": SESSION_ID, "status": "ready"}, "s1"),
    )
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "ready"
    assert hass.states.get(QR).state == "unavailable"


async def test_remove_entry_deletes_webhook(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.clear_requests()
    mock_server(
        aioclient_mock,
        webhooks=[{"id": WEBHOOK_ID, "url": f"{HA_URL}/api/webhook/{HOOK_ID}"}],
    )
    await hass.config_entries.async_remove(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert ("DELETE", f"{BASE}/webhooks/{WEBHOOK_ID}") in [
        (c[0].upper(), str(c[1])) for c in aioclient_mock.mock_calls
    ]


async def test_notify_sends_to_default_chat(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.post(
        f"{BASE}/messages/send-text",
        status=201,
        json={"messageId": "m", "timestamp": 1},
    )
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": NOTIFY, "message": "Tür offen", "title": "Alarm"},
        blocking=True,
    )
    sent = aioclient_mock.mock_calls[-1]
    assert sent[2] == {"chatId": CHAT, "text": "*Alarm*\nTür offen"}


async def test_notify_without_default_chat(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    hass.config_entries.async_update_entry(setup_entry, options={})
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": NOTIFY, "message": "x"},
            blocking=True,
        )


async def test_service_send_message_by_name(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.post(
        f"{BASE}/messages/send-text",
        status=201,
        json={"messageId": "m9", "timestamp": 1},
    )
    response = await hass.services.async_call(
        DOMAIN,
        "send_message",
        {"session": SESSION_NAME, "chat_id": "+49 151 00000003", "text": "hi"},
        blocking=True,
        return_response=True,
    )
    assert response == {"message_id": "m9", "timestamp": 1}
    assert aioclient_mock.mock_calls[-1][2]["chatId"] == "4915100000003@c.us"


async def test_service_unknown_session(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "send_message",
            {"session": "nope", "chat_id": CHAT, "text": "hi"},
            blocking=True,
        )


async def test_send_media_path_not_allowed(
    hass: HomeAssistant, setup_entry: MockConfigEntry, tmp_path: Path
) -> None:
    file = tmp_path / "snap.jpg"
    file.write_bytes(b"jpeg")
    with pytest.raises(ServiceValidationError, match="allowlist_external_dirs"):
        await hass.services.async_call(
            DOMAIN,
            "send_media",
            {"session": SESSION_NAME, "chat_id": CHAT, "path": str(file)},
            blocking=True,
        )


async def test_send_media_path(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    tmp_path: Path,
) -> None:
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    file = tmp_path / "snap.jpg"
    file.write_bytes(b"jpeg")
    aioclient_mock.post(
        f"{BASE}/messages/send-image",
        status=201,
        json={"messageId": "m", "timestamp": 1},
    )
    await hass.services.async_call(
        DOMAIN,
        "send_media",
        {"session": SESSION_ID, "chat_id": CHAT, "path": str(file), "caption": "c"},
        blocking=True,
    )
    assert aioclient_mock.mock_calls[-1][2] == {
        "chatId": CHAT,
        "base64": base64.b64encode(b"jpeg").decode(),
        "mimetype": "image/jpeg",
        "caption": "c",
        "filename": "snap.jpg",
    }


async def test_send_media_url_and_path_exclusive(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    with pytest.raises(Exception, match="source"):
        await hass.services.async_call(
            DOMAIN,
            "send_media",
            {
                "session": SESSION_NAME,
                "chat_id": CHAT,
                "url": "https://x/a.jpg",
                "path": "/tmp/a.jpg",
            },
            blocking=True,
        )


async def test_device_trigger_with_from_filter(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    hass.config.country = "DE"
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, SESSION_ID), setup_entry.entry_id
    )
    calls: list = []
    hass.services.async_register("test", "record", lambda call: calls.append(call))
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "triggers": {
                    "platform": "device",
                    "domain": DOMAIN,
                    "device_id": device.id,
                    "type": "message_received",
                    "from": "0151 00000009",
                },
                "actions": {"action": "test.record"},
            }
        },
    )
    await _post(
        hass_client_no_auth,
        _delivery("message.received", {"from": "4915100000009@c.us"}, "t1"),
    )
    await _post(
        hass_client_no_auth,
        _delivery("message.received", {"from": "4915199999999@c.us"}, "t2"),
    )
    # Sender hidden behind a LID, resolved by OpenWA (RESOLVE_LID_TO_PHONE).
    await _post(
        hass_client_no_auth,
        _delivery(
            "message.received",
            {"from": "209569389236259@lid", "senderPhone": "4915100000009"},
            "t3",
        ),
    )
    # Same LID sender without resolution cannot match a phone filter.
    await _post(
        hass_client_no_auth,
        _delivery("message.received", {"from": "209569389236259@lid"}, "t4"),
    )
    await hass.async_block_till_done()
    assert len(calls) == 2


async def test_event_sender_phone(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    events = async_capture_events(hass, EVENT_OPENWA)
    await _post(
        hass_client_no_auth,
        _delivery(
            "message.received",
            {"from": "209569389236259@lid", "senderPhone": "4915100000009"},
            "p1",
        ),
    )
    await _post(
        hass_client_no_auth,
        _delivery("message.received", {"from": "4915100000009@c.us"}, "p2"),
    )
    await hass.async_block_till_done()
    assert events[0].data["from"] == "209569389236259@lid"
    assert events[0].data["sender_phone"] == "4915100000009@c.us"
    assert events[1].data["sender_phone"] is None


async def test_service_national_number(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    hass.config.country = "DE"
    aioclient_mock.post(
        f"{BASE}/messages/send-text",
        status=201,
        json={"messageId": "m", "timestamp": 1},
    )
    await hass.services.async_call(
        DOMAIN,
        "send_message",
        {"session": SESSION_NAME, "chat_id": "0151 00000003", "text": "hi"},
        blocking=True,
    )
    assert aioclient_mock.mock_calls[-1][2]["chatId"] == "4915100000003@c.us"


async def test_service_national_number_without_country(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    hass.config.country = None
    with pytest.raises(ServiceValidationError, match="country code"):
        await hass.services.async_call(
            DOMAIN,
            "send_message",
            {"session": SESSION_NAME, "chat_id": "0151 00000003", "text": "hi"},
            blocking=True,
        )


async def test_own_messages_option_resyncs_webhook_events(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.clear_requests()
    mock_server(
        aioclient_mock,
        webhooks=[{"id": WEBHOOK_ID, "url": f"{HA_URL}/api/webhook/{HOOK_ID}"}],
    )
    hass.config_entries.async_update_entry(
        setup_entry, options={**setup_entry.options, "own_messages": "all"}
    )
    await hass.async_block_till_done()

    put = [c for c in aioclient_mock.mock_calls if c[0].upper() == "PUT"]
    assert put, "reload must re-sync the webhook"
    assert "message.sent" in put[-1][2]["events"]
    assert "message.received" in put[-1][2]["events"]


async def test_message_sent_event(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    events = async_capture_events(hass, EVENT_OPENWA)
    await _post(
        hass_client_no_auth,
        _delivery(
            "message.sent",
            {"from": "4915100000000@c.us", "fromMe": True, "body": "note"},
            "s-1",
        ),
    )
    await hass.async_block_till_done()
    assert events[0].data["event_type"] == "message.sent"
    assert events[0].data["data"]["fromMe"] is True
    assert events[0].data["sender_phone"] is None


async def test_message_sent_trigger_offered_only_with_option(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, SESSION_ID), setup_entry.entry_id
    )
    types = {t["type"] for t in await async_get_triggers(hass, device.id)}
    assert types == {"message_received"}

    aioclient_mock.clear_requests()
    mock_server(aioclient_mock)
    hass.config_entries.async_update_entry(
        setup_entry, options={**setup_entry.options, "own_messages": "all"}
    )
    await hass.async_block_till_done()
    types = {t["type"] for t in await async_get_triggers(hass, device.id)}
    assert types == {"message_received", "message_sent"}


async def test_message_sent_device_trigger(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, SESSION_ID), setup_entry.entry_id
    )
    calls: list = []
    hass.services.async_register("test", "record", lambda call: calls.append(call))
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "triggers": {
                    "platform": "device",
                    "domain": DOMAIN,
                    "device_id": device.id,
                    "type": "message_sent",
                },
                "actions": {"action": "test.record"},
            }
        },
    )
    await _post(
        hass_client_no_auth,
        _delivery("message.sent", {"from": "x@c.us", "fromMe": True}, "ms1"),
    )
    await _post(
        hass_client_no_auth,
        _delivery("message.received", {"from": "y@c.us"}, "mr1"),
    )
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_sender_filter_rejected_for_message_sent(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    with pytest.raises(vol.Invalid):
        await async_validate_trigger_config(
            hass,
            {
                "platform": "device",
                "domain": DOMAIN,
                "device_id": "abc",
                "type": "message_sent",
                "from": "+49 151 1",
            },
        )


OWN = "4915100000000"  # phone of SESSION_READY
SELF_LID = "111111111111111@lid"
OTHER_LID = "222222222222222@lid"


async def _set_own_messages(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mode: str,
) -> None:
    aioclient_mock.clear_requests()
    mock_server(aioclient_mock)
    aioclient_mock.get(f"{BASE}/contacts/{SELF_LID}/phone", json={"phone": OWN})
    aioclient_mock.get(
        f"{BASE}/contacts/{OTHER_LID}/phone", json={"phone": "4915199999999"}
    )
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "own_messages": mode}
    )
    await hass.async_block_till_done()


def _sent(to: str, key: str) -> dict:
    return _delivery(
        "message.sent",
        {"from": f"{OWN}@c.us", "to": to, "fromMe": True, "body": "b"},
        key,
    )


@pytest.mark.parametrize(
    ("to", "expected"),
    [
        (SELF_LID, True),  # self chat behind a LID (seen live)
        (f"{OWN}@c.us", True),  # classic self chat
        (OTHER_LID, False),
        ("4915199999999@c.us", False),
        ("120363000000000000@g.us", False),
    ],
)
async def test_to_self_detection(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
    to: str,
    expected: bool,
) -> None:
    await _set_own_messages(hass, setup_entry, aioclient_mock, "all")
    events = async_capture_events(hass, EVENT_OPENWA)
    await _post(hass_client_no_auth, _sent(to, "k"))
    await hass.async_block_till_done()
    assert events[0].data["to_self"] is expected


async def test_self_mode_drops_messages_to_others(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    await _set_own_messages(hass, setup_entry, aioclient_mock, "self")
    events = async_capture_events(hass, EVENT_OPENWA)
    assert await _post(hass_client_no_auth, _sent(OTHER_LID, "o1")) == 200
    assert await _post(hass_client_no_auth, _sent(SELF_LID, "s1")) == 200
    await hass.async_block_till_done()
    assert [e.data["to_self"] for e in events] == [True]


async def test_lid_resolved_once(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    await _set_own_messages(hass, setup_entry, aioclient_mock, "self")
    await _post(hass_client_no_auth, _sent(SELF_LID, "c1"))
    await _post(hass_client_no_auth, _sent(SELF_LID, "c2"))
    await hass.async_block_till_done()
    resolves = [c for c in aioclient_mock.mock_calls if c[1].path.endswith("/phone")]
    assert len(resolves) == 1


async def test_unresolvable_lid_is_not_self(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    await _set_own_messages(hass, setup_entry, aioclient_mock, "all")
    aioclient_mock.clear_requests()
    mock_server(aioclient_mock)
    aioclient_mock.get(f"{BASE}/contacts/{SELF_LID}/phone", exc=TimeoutError())
    events = async_capture_events(hass, EVENT_OPENWA)
    await _post(hass_client_no_auth, _sent(SELF_LID, "u1"))
    await hass.async_block_till_done()
    assert events[0].data["to_self"] is False


async def test_received_message_is_not_self(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    events = async_capture_events(hass, EVENT_OPENWA)
    await _post(
        hass_client_no_auth,
        _delivery("message.received", {"from": SELF_LID, "to": SELF_LID}, "r1"),
    )
    await hass.async_block_till_done()
    assert events[0].data["to_self"] is False
