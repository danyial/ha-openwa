"""openwa.send_message and openwa.send_media."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import OpenWAError, RateLimited, SendResult
from .const import (
    ATTR_CAPTION,
    ATTR_CHAT_ID,
    ATTR_FILENAME,
    ATTR_KIND,
    ATTR_PATH,
    ATTR_QUOTED_MESSAGE_ID,
    ATTR_SESSION,
    ATTR_TEXT,
    ATTR_URL,
    DOMAIN,
    MAX_MEDIA_BYTES,
    MEDIA_KINDS,
    SERVICE_SEND_MEDIA,
    SERVICE_SEND_MESSAGE,
)
from .helpers import normalize_chat_id

if TYPE_CHECKING:
    from .coordinator import OpenWASessionCoordinator


SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SESSION): cv.string,
        vol.Required(ATTR_CHAT_ID): cv.string,
        vol.Required(ATTR_TEXT): cv.string,
        vol.Optional(ATTR_QUOTED_MESSAGE_ID): cv.string,
    }
)

SEND_MEDIA_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(ATTR_SESSION): cv.string,
            vol.Required(ATTR_CHAT_ID): cv.string,
            vol.Exclusive(ATTR_URL, "source"): cv.url,
            vol.Exclusive(ATTR_PATH, "source"): cv.string,
            vol.Optional(ATTR_CAPTION): cv.string,
            vol.Optional(ATTR_KIND): vol.In(MEDIA_KINDS),
            vol.Optional(ATTR_FILENAME): cv.string,
        }
    ),
    cv.has_at_least_one_key(ATTR_URL, ATTR_PATH),
)


def kind_for(mimetype: str | None) -> str:
    """Map a MIME type to an OpenWA send endpoint."""
    major = (mimetype or "").split("/", 1)[0]
    return major if major in ("image", "video", "audio") else "document"


def _find_session(hass: HomeAssistant, session: str) -> OpenWASessionCoordinator:
    """Resolve a session by UUID or name across all loaded entries."""
    matches = [
        coordinator
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        for coordinator in entry.runtime_data.coordinators.values()
        if session in (coordinator.session_id, coordinator.session_name)
    ]
    if len(matches) != 1:
        raise ServiceValidationError(
            f"OpenWA session {session!r} "
            + ("is ambiguous" if matches else "is not configured")
        )
    return matches[0]


def _response(result: SendResult) -> ServiceResponse:
    return {"message_id": result.message_id, "timestamp": result.timestamp}


def _raise(err: OpenWAError) -> None:
    if isinstance(err, RateLimited):
        raise HomeAssistantError(
            f"OpenWA rate limit, retry after {err.retry_after or '?'} s"
        ) from err
    raise HomeAssistantError(f"Sending failed: {err}") from err


def _chat_id(hass: HomeAssistant, call: ServiceCall) -> str:
    """Normalize chat_id; national numbers use the HA country setting."""
    try:
        return normalize_chat_id(call.data[ATTR_CHAT_ID], hass.config.country)
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err


def _read_file(path: Path) -> bytes:
    if not path.is_file():
        raise ServiceValidationError(f"{path} does not exist")
    if path.stat().st_size > MAX_MEDIA_BYTES:
        raise ServiceValidationError(
            f"{path} is larger than {MAX_MEDIA_BYTES // (1024 * 1024)} MB"
        )
    return path.read_bytes()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration services."""

    async def send_message(call: ServiceCall) -> ServiceResponse:
        coordinator = _find_session(hass, call.data[ATTR_SESSION])
        chat_id = _chat_id(hass, call)
        try:
            result = await coordinator.client.send_text(
                coordinator.session_id,
                chat_id,
                call.data[ATTR_TEXT],
                call.data.get(ATTR_QUOTED_MESSAGE_ID),
            )
        except OpenWAError as err:
            _raise(err)
        return _response(result)

    async def send_media(call: ServiceCall) -> ServiceResponse:
        coordinator = _find_session(hass, call.data[ATTR_SESSION])
        chat_id = _chat_id(hass, call)
        url: str | None = call.data.get(ATTR_URL)
        filename: str | None = call.data.get(ATTR_FILENAME)
        payload: str | None = None
        mimetype: str | None = None

        if path_str := call.data.get(ATTR_PATH):
            path = Path(path_str)
            if not hass.config.is_allowed_path(str(path)):
                raise ServiceValidationError(
                    f"{path} is not in allowlist_external_dirs"
                )
            raw = await hass.async_add_executor_job(_read_file, path)
            payload = base64.b64encode(raw).decode()
            mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            filename = filename or path.name
        else:
            mimetype = mimetypes.guess_type(url or "")[0]

        kind = call.data.get(ATTR_KIND) or kind_for(mimetype)
        try:
            result = await coordinator.client.send_media(
                coordinator.session_id,
                kind,
                chat_id,
                url=url,
                base64=payload,
                mimetype=mimetype if payload else None,
                caption=call.data.get(ATTR_CAPTION),
                filename=filename,
            )
        except OpenWAError as err:
            _raise(err)
        return _response(result)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        send_message,
        schema=SEND_MESSAGE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MEDIA,
        send_media,
        schema=SEND_MEDIA_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
