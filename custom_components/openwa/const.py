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
