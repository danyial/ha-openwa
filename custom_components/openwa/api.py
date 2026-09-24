"""Async client for the OpenWA REST API (tested against 0.23.x)."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

import aiohttp
from homeassistant.util.json import json_loads

from .const import REQUEST_TIMEOUT


class OpenWAError(Exception):
    """Base error for OpenWA API calls."""


class CannotConnect(OpenWAError):
    """Server unreachable or timed out."""


class InvalidAuth(OpenWAError):
    """API key rejected."""


class SessionNotAllowed(OpenWAError):
    """Key is valid but not authorized for this session (allowedSessions)."""


class RateLimited(OpenWAError):
    """Server throttled the request."""

    def __init__(self, message: str, retry_after: float | None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ApiError(OpenWAError):
    """Unexpected non-2xx response."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


@dataclass(frozen=True, slots=True)
class SendResult:
    """Response of a send-* call."""

    message_id: str
    timestamp: Any


class OpenWAClient:
    """Thin wrapper around the endpoints the integration needs."""

    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str) -> None:
        self._session = session
        self._base = url.rstrip("/")
        self._api_key = api_key

    @property
    def base_url(self) -> str:
        """Return the server base URL."""
        return self._base

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        headers = {"X-API-Key": self._api_key} if auth else {}
        try:
            async with self._session.request(
                method,
                f"{self._base}{path}",
                json=json,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status == HTTPStatus.NO_CONTENT:
                    return None
                body = await _read_body(resp)
                if resp.status < 400:
                    return body
                await self._raise_for(resp, body, path)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CannotConnect(f"{method} {path}: {err}") from err
        return None  # unreachable, keeps type checkers calm

    async def _raise_for(
        self, resp: aiohttp.ClientResponse, body: Any, path: str
    ) -> None:
        message = _error_message(body)
        if resp.status == HTTPStatus.UNAUTHORIZED:
            # OpenWA answers 401 both for a bad key and for a session outside
            # the key's allowedSessions. Only the former needs reauth.
            if path != "/api/auth/validate" and await self._key_is_valid():
                raise SessionNotAllowed(message)
            raise InvalidAuth(message)
        if resp.status == HTTPStatus.FORBIDDEN:
            raise SessionNotAllowed(message)
        if resp.status == HTTPStatus.TOO_MANY_REQUESTS:
            raise RateLimited(message, _retry_after(resp, body))
        raise ApiError(resp.status, message)

    async def _key_is_valid(self) -> bool:
        try:
            await self.validate()
        except InvalidAuth:
            return False
        return True

    # Auth / health

    async def validate(self) -> str:
        """Validate the key, return its role."""
        data = await self._request("POST", "/api/auth/validate")
        return str(data.get("role", ""))

    async def version(self) -> str | None:
        """Return the server version (only exposed to authenticated callers)."""
        data = await self._request("GET", "/api/health")
        return data.get("version") if isinstance(data, dict) else None

    async def ready(self) -> bool:
        """Return True if the server and its databases are up."""
        try:
            await self._request("GET", "/api/health/ready", auth=False)
        except OpenWAError:
            return False
        return True

    # Sessions

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List sessions visible to this key."""
        return list(await self._request("GET", "/api/sessions") or [])

    async def get_session(self, session_id: str) -> dict[str, Any]:
        """Return one session (SessionResponseDto)."""
        return await self._request("GET", f"/api/sessions/{session_id}")

    async def get_qr(self, session_id: str) -> str | None:
        """Return the QR as PNG data URL, or None if the engine has none."""
        try:
            data = await self._request("GET", f"/api/sessions/{session_id}/qr")
        except ApiError as err:
            if err.status == HTTPStatus.BAD_REQUEST:
                return None
            raise
        return data.get("qrCode") if isinstance(data, dict) else None

    async def session_action(self, session_id: str, action: str) -> None:
        """Run a lifecycle action: start, stop or logout."""
        if action not in ("start", "stop", "logout"):
            raise ValueError(action)
        await self._request("POST", f"/api/sessions/{session_id}/{action}")

    # Messages

    async def send_text(
        self,
        session_id: str,
        chat_id: str,
        text: str,
        quoted_message_id: str | None = None,
    ) -> SendResult:
        """Send a text message."""
        body: dict[str, Any] = {"chatId": chat_id, "text": text}
        if quoted_message_id:
            body["quotedMessageId"] = quoted_message_id
        data = await self._request(
            "POST", f"/api/sessions/{session_id}/messages/send-text", json=body
        )
        return SendResult(data.get("messageId", ""), data.get("timestamp"))

    async def send_media(
        self,
        session_id: str,
        kind: str,
        chat_id: str,
        *,
        url: str | None = None,
        base64: str | None = None,
        mimetype: str | None = None,
        caption: str | None = None,
        filename: str | None = None,
    ) -> SendResult:
        """Send image, video, audio or document by URL or base64."""
        if kind not in ("image", "video", "audio", "document"):
            raise ValueError(kind)
        if (url is None) == (base64 is None):
            raise ValueError("exactly one of url or base64 is required")
        if base64 is not None and not mimetype:
            raise ValueError("mimetype is required with base64")
        body: dict[str, Any] = {"chatId": chat_id}
        for key, value in (
            ("url", url),
            ("base64", base64),
            ("mimetype", mimetype),
            ("caption", caption),
            ("filename", filename),
        ):
            if value:
                body[key] = value
        data = await self._request(
            "POST", f"/api/sessions/{session_id}/messages/send-{kind}", json=body
        )
        return SendResult(data.get("messageId", ""), data.get("timestamp"))

    # Webhooks

    async def list_webhooks(self, session_id: str) -> list[dict[str, Any]]:
        """List webhooks of a session."""
        return list(
            await self._request("GET", f"/api/sessions/{session_id}/webhooks") or []
        )

    async def create_webhook(
        self, session_id: str, url: str, events: list[str], secret: str
    ) -> dict[str, Any]:
        """Create a webhook, return WebhookResponseDto."""
        return await self._request(
            "POST",
            f"/api/sessions/{session_id}/webhooks",
            json={"url": url, "events": events, "secret": secret, "retryCount": 3},
        )

    async def update_webhook(
        self,
        session_id: str,
        webhook_id: str,
        url: str,
        events: list[str],
        secret: str,
    ) -> dict[str, Any]:
        """Replace URL, events and secret of a webhook."""
        return await self._request(
            "PUT",
            f"/api/sessions/{session_id}/webhooks/{webhook_id}",
            json={"url": url, "events": events, "secret": secret},
        )

    async def delete_webhook(self, session_id: str, webhook_id: str) -> None:
        """Delete a webhook; a missing one counts as deleted."""
        try:
            await self._request(
                "DELETE", f"/api/sessions/{session_id}/webhooks/{webhook_id}"
            )
        except ApiError as err:
            if err.status != HTTPStatus.NOT_FOUND:
                raise

    async def test_webhook(self, session_id: str, webhook_id: str) -> dict[str, Any]:
        """Trigger a test delivery, return {success, statusCode|error}."""
        return await self._request(
            "POST", f"/api/sessions/{session_id}/webhooks/{webhook_id}/test"
        )


async def _read_body(resp: aiohttp.ClientResponse) -> Any:
    text = await resp.text()
    if not text:
        return None
    try:
        return json_loads(text)
    except ValueError:
        return text


def _error_message(body: Any) -> str:
    if isinstance(body, dict):
        message = body.get("message", "")
        if isinstance(message, list):
            return "; ".join(str(m) for m in message)
        return str(message)
    return str(body)[:200]


def _retry_after(resp: aiohttp.ClientResponse, body: Any) -> float | None:
    # Throttler sends a Retry-After header; send pacing only puts
    # retryAfterSeconds into the body.
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    if isinstance(body, dict) and body.get("retryAfterSeconds") is not None:
        try:
            return float(body["retryAfterSeconds"])
        except TypeError, ValueError:
            pass
    return None


__all__ = [
    "ApiError",
    "CannotConnect",
    "InvalidAuth",
    "OpenWAClient",
    "OpenWAError",
    "RateLimited",
    "SendResult",
    "SessionNotAllowed",
]
