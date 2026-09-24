"""Tests for the OpenWA API client."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.openwa.api import (
    ApiError,
    CannotConnect,
    InvalidAuth,
    OpenWAClient,
    RateLimited,
    SessionNotAllowed,
)

from .const import API_KEY, QR_DATA_URL, SESSION_ID, SESSION_READY, URL, WEBHOOK_ID

UNAUTHORIZED_SESSION = {
    "statusCode": 401,
    "message": "API key not authorized for this session",
}
UNAUTHORIZED_KEY = {"statusCode": 401, "message": "Invalid API key"}


@pytest.fixture
async def client(
    aioclient_mock: AiohttpClientMocker,
) -> AsyncIterator[OpenWAClient]:
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield OpenWAClient(session, URL + "/", API_KEY)
    await session.close()


@pytest.fixture
def mock(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    return aioclient_mock


async def test_validate_sends_key(
    client: OpenWAClient, mock: AiohttpClientMocker
) -> None:
    mock.post(f"{URL}/api/auth/validate", json={"valid": True, "role": "operator"})
    assert await client.validate() == "operator"
    (_, url, _, headers) = mock.mock_calls[0]
    assert str(url) == f"{URL}/api/auth/validate"
    assert headers == {"X-API-Key": API_KEY}


async def test_invalid_key(client: OpenWAClient, mock: AiohttpClientMocker) -> None:
    mock.post(f"{URL}/api/auth/validate", status=401, json=UNAUTHORIZED_KEY)
    with pytest.raises(InvalidAuth):
        await client.validate()


async def test_401_with_valid_key_is_session_not_allowed(
    client: OpenWAClient, mock: AiohttpClientMocker
) -> None:
    mock.get(f"{URL}/api/sessions/{SESSION_ID}", status=401, json=UNAUTHORIZED_SESSION)
    mock.post(f"{URL}/api/auth/validate", json={"valid": True, "role": "operator"})
    with pytest.raises(SessionNotAllowed):
        await client.get_session(SESSION_ID)


async def test_401_with_bad_key_is_invalid_auth(
    client: OpenWAClient, mock: AiohttpClientMocker
) -> None:
    mock.get(f"{URL}/api/sessions/{SESSION_ID}", status=401, json=UNAUTHORIZED_KEY)
    mock.post(f"{URL}/api/auth/validate", status=401, json=UNAUTHORIZED_KEY)
    with pytest.raises(InvalidAuth):
        await client.get_session(SESSION_ID)


async def test_connection_error(
    client: OpenWAClient, mock: AiohttpClientMocker
) -> None:
    mock.get(f"{URL}/api/sessions", exc=aiohttp.ClientConnectionError("boom"))
    with pytest.raises(CannotConnect):
        await client.list_sessions()


async def test_timeout(client: OpenWAClient, mock: AiohttpClientMocker) -> None:
    mock.get(f"{URL}/api/sessions", exc=TimeoutError())
    with pytest.raises(CannotConnect):
        await client.list_sessions()


async def test_get_session(client: OpenWAClient, mock: AiohttpClientMocker) -> None:
    mock.get(f"{URL}/api/sessions/{SESSION_ID}", json=SESSION_READY)
    assert (await client.get_session(SESSION_ID))["status"] == "ready"


async def test_version(client: OpenWAClient, mock: AiohttpClientMocker) -> None:
    mock.get(
        f"{URL}/api/health",
        json={"status": "ok", "timestamp": "x", "version": "0.23.6"},
    )
    assert await client.version() == "0.23.6"


async def test_ready_false_on_error(
    client: OpenWAClient, mock: AiohttpClientMocker
) -> None:
    mock.get(f"{URL}/api/health/ready", status=503, json={"status": "error"})
    assert await client.ready() is False


async def test_qr(client: OpenWAClient, mock: AiohttpClientMocker) -> None:
    mock.get(
        f"{URL}/api/sessions/{SESSION_ID}/qr",
        json={"qrCode": QR_DATA_URL, "status": "qr_ready"},
    )
    assert await client.get_qr(SESSION_ID) == QR_DATA_URL


async def test_qr_400_means_none(
    client: OpenWAClient, mock: AiohttpClientMocker
) -> None:
    mock.get(
        f"{URL}/api/sessions/{SESSION_ID}/qr",
        status=400,
        json={
            "message": "Session is already authenticated, no QR code needed",
            "error": "Bad Request",
            "statusCode": 400,
        },
    )
    assert await client.get_qr(SESSION_ID) is None


async def test_session_action_rejects_unknown(client: OpenWAClient) -> None:
    with pytest.raises(ValueError):
        await client.session_action(SESSION_ID, "force-kill")


async def test_send_text(client: OpenWAClient, mock: AiohttpClientMocker) -> None:
    path = f"{URL}/api/sessions/{SESSION_ID}/messages/send-text"
    mock.post(path, status=201, json={"messageId": "m1", "timestamp": 1})
    result = await client.send_text(SESSION_ID, "4915@c.us", "hi", "q1")
    assert result.message_id == "m1"
    assert mock.mock_calls[0][2] == {
        "chatId": "4915@c.us",
        "text": "hi",
        "quotedMessageId": "q1",
    }


async def test_send_media_base64(
    client: OpenWAClient, mock: AiohttpClientMocker
) -> None:
    path = f"{URL}/api/sessions/{SESSION_ID}/messages/send-image"
    mock.post(path, status=201, json={"messageId": "m2", "timestamp": 1})
    await client.send_media(
        SESSION_ID, "image", "4915@c.us", base64="QUJD", mimetype="image/jpeg"
    )
    assert mock.mock_calls[0][2] == {
        "chatId": "4915@c.us",
        "base64": "QUJD",
        "mimetype": "image/jpeg",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"url": "http://x/a.jpg", "base64": "QUJD", "mimetype": "image/jpeg"},
        {"base64": "QUJD"},
    ],
)
async def test_send_media_validates_args(client: OpenWAClient, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        await client.send_media(SESSION_ID, "image", "4915@c.us", **kwargs)


async def test_rate_limited_header(
    client: OpenWAClient, mock: AiohttpClientMocker
) -> None:
    mock.post(
        f"{URL}/api/sessions/{SESSION_ID}/messages/send-text",
        status=429,
        headers={"Retry-After": "7"},
        json={"statusCode": 429, "message": "ThrottlerException"},
    )
    with pytest.raises(RateLimited) as exc:
        await client.send_text(SESSION_ID, "4915@c.us", "hi")
    assert exc.value.retry_after == 7


async def test_rate_limited_pacing_body(
    client: OpenWAClient, mock: AiohttpClientMocker
) -> None:
    mock.post(
        f"{URL}/api/sessions/{SESSION_ID}/messages/send-text",
        status=429,
        json={
            "statusCode": 429,
            "code": "SEND_PACING_LIMITED",
            "message": "Send pacing limit reached",
            "retryAfterSeconds": 12,
        },
    )
    with pytest.raises(RateLimited) as exc:
        await client.send_text(SESSION_ID, "4915@c.us", "hi")
    assert exc.value.retry_after == 12


async def test_api_error_joins_validation_messages(
    client: OpenWAClient, mock: AiohttpClientMocker
) -> None:
    mock.post(
        f"{URL}/api/sessions/{SESSION_ID}/messages/send-text",
        status=400,
        json={"statusCode": 400, "message": ["chatId must be a string", "x"]},
    )
    with pytest.raises(ApiError, match="chatId must be a string; x"):
        await client.send_text(SESSION_ID, "4915@c.us", "hi")


async def test_webhook_roundtrip(
    client: OpenWAClient, mock: AiohttpClientMocker
) -> None:
    base = f"{URL}/api/sessions/{SESSION_ID}/webhooks"
    mock.post(base, status=201, json={"id": WEBHOOK_ID, "active": True})
    mock.post(f"{base}/{WEBHOOK_ID}/test", json={"success": True, "statusCode": 200})
    mock.delete(f"{base}/{WEBHOOK_ID}", status=204)

    created = await client.create_webhook(
        SESSION_ID, "https://ha/api/webhook/x", ["session.status"], "s" * 32
    )
    assert created["id"] == WEBHOOK_ID
    assert (await client.test_webhook(SESSION_ID, WEBHOOK_ID))["success"] is True
    await client.delete_webhook(SESSION_ID, WEBHOOK_ID)


async def test_delete_missing_webhook_is_ok(
    client: OpenWAClient, mock: AiohttpClientMocker
) -> None:
    mock.delete(
        f"{URL}/api/sessions/{SESSION_ID}/webhooks/{WEBHOOK_ID}",
        status=404,
        json={"statusCode": 404, "message": "Webhook not found"},
    )
    await client.delete_webhook(SESSION_ID, WEBHOOK_ID)
