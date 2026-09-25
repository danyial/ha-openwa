"""Constants for the OpenWA integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "openwa"

CONF_SESSIONS: Final = "sessions"
CONF_WEBHOOK_ID: Final = "webhook_id"
CONF_WEBHOOK_URL: Final = "webhook_url"
CONF_WEBHOOK_SECRET: Final = "webhook_secret"
CONF_DEFAULT_CHAT_IDS: Final = "default_chat_ids"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_OWN_MESSAGES: Final = "own_messages"

DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=60)
REQUEST_TIMEOUT: Final = 15

EVENT_OPENWA: Final = "openwa_event"

# Events OpenWA delivers to our webhook. Deliberately no "*".
WEBHOOK_EVENTS: Final = [
    "message.received",
    "message.ack",
    "session.status",
    "session.qr",
    "session.authenticated",
    "session.disconnected",
]
# Own messages (fromMe) arrive as message.sent. Opt-in, because Home
# Assistant's own sends produce them too.
EVENT_MESSAGE_SENT: Final = "message.sent"
OWN_MESSAGES_OFF: Final = "off"
OWN_MESSAGES_SELF: Final = "self"  # only notes to yourself
OWN_MESSAGES_ALL: Final = "all"
OWN_MESSAGE_MODES: Final = [OWN_MESSAGES_OFF, OWN_MESSAGES_SELF, OWN_MESSAGES_ALL]


def webhook_events(own_messages: str) -> list[str]:
    """Events to subscribe, depending on the own_messages option."""
    if own_messages == OWN_MESSAGES_OFF:
        return list(WEBHOOK_EVENTS)
    return [*WEBHOOK_EVENTS, EVENT_MESSAGE_SENT]


SESSION_EVENTS: Final = frozenset(
    {"session.status", "session.qr", "session.authenticated", "session.disconnected"}
)

STATUS_READY: Final = "ready"
STATUS_QR_READY: Final = "qr_ready"
SESSION_STATUSES: Final = [
    "created",
    "initializing",
    "qr_ready",
    "authenticating",
    "ready",
    "disconnected",
    "action_required",
    "failed",
]

# Tested against OpenWA 0.23.x; warn outside this range.
SUPPORTED_VERSION_PREFIX: Final = "0.23."

# JSON body limit on the server is 25 MB; base64 inflates by 4/3.
MAX_MEDIA_BYTES: Final = 18 * 1024 * 1024

MEDIA_KINDS: Final = ["image", "video", "audio", "document"]

SERVICE_SEND_MESSAGE: Final = "send_message"
SERVICE_SEND_MEDIA: Final = "send_media"

ATTR_SESSION: Final = "session"
ATTR_CHAT_ID: Final = "chat_id"
ATTR_TEXT: Final = "text"
ATTR_QUOTED_MESSAGE_ID: Final = "quoted_message_id"
ATTR_URL: Final = "url"
ATTR_PATH: Final = "path"
ATTR_CAPTION: Final = "caption"
ATTR_KIND: Final = "kind"
ATTR_FILENAME: Final = "filename"
