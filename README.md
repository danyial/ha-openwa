# ha-openwa

Home Assistant custom integration for [OpenWA](https://github.com/rmyndharis/OpenWA), a self-hosted WhatsApp API gateway.

Send WhatsApp messages and media from automations, receive incoming messages as events, and see each session's connection state and pairing QR code in Home Assistant.

Tested with OpenWA **0.23.x** and Home Assistant **2026.9**. OpenWA is pre-1.0 and its API still moves; the integration logs a warning when the server reports another version.

> **Risk:** OpenWA drives an unofficial WhatsApp client. WhatsApp can ban numbers that use it. Use a secondary number, don't send bulk messages, and leave OpenWA's `RATE_LIMIT_*` settings on.

## What you get

Per OpenWA session (one device each):

| Entity | Description |
|---|---|
| `sensor.<session>_status` | `created`, `initializing`, `qr_ready`, `authenticating`, `ready`, `disconnected`, `action_required`, `failed`. Attributes: `phone`, `pushName`, `connectedAt`, `lastError`, `engineLoaded` |
| `binary_sensor.<session>_connected` | on while status is `ready` |
| `image.<session>_pairing_qr_code` | pairing QR, available only while status is `qr_ready` |
| `button.<session>_start` / `_stop` / `_log_out` | session lifecycle |
| `notify.<session>` | sends to the session's default chat (set in the options) |

Status changes arrive by webhook push. Polling every 60 s (configurable) is the fallback.

## Server preparation

1. **API key:** create an **OPERATOR** key in OpenWA with `allowedSessions` set to the session(s) Home Assistant should use. Don't use the admin key.
2. **Session:** the integration only attaches to existing sessions. Create and pair the session in OpenWA first, or pair it later through the QR image entity.
3. **Webhook target (SSRF guard):** OpenWA refuses webhook URLs that resolve to private addresses. If Home Assistant is on your LAN, set this on the OpenWA server:

   ```
   SSRF_ALLOWED_HOSTS=ha.example.com
   ```

   The value is compared with the **host name in the webhook URL**, not with the resolved IP. If the URL uses `ha.example.com`, allowlisting only its IP does not work.

## Installation

Copy `custom_components/openwa` into your Home Assistant `config/custom_components/` directory and restart.

HACS can only add custom repositories hosted on GitHub. The repository layout is HACS-compatible, but installing through HACS needs a GitHub mirror of this repository.

## Setup

*Settings → Devices & services → Add integration → OpenWA*

1. Server URL and API key.
2. Pick the sessions to add.
3. Confirm the Home Assistant URL that OpenWA should post events to. The default is your external URL. The integration creates one webhook per session in OpenWA and sends a test delivery. If the test fails, nothing is saved and the created webhooks are removed again; the usual cause is `SSRF_ALLOWED_HOSTS`.

The options let you set a default chat per session for the notify entity and change the polling interval.

Removing the integration deletes its webhooks in OpenWA.

## Sending

Chat IDs: `4915112345678@c.us` for a person, `<id>@g.us` for a group. A phone number such as `+49 151 1234 5678` is converted to the `@c.us` form.

```yaml
action: notify.send_message
target:
  entity_id: notify.home_assistant
data:
  title: Alarm
  message: Front door opened
```

```yaml
action: openwa.send_message
data:
  session: home-assistant          # session name or id
  chat_id: "+49 151 12345678"
  text: Hello from Home Assistant
```

```yaml
action: openwa.send_media
data:
  session: home-assistant
  chat_id: "4915112345678@c.us"
  path: /config/www/snapshot.jpg   # or url: https://…
  caption: Front door
```

`path` must be inside [`allowlist_external_dirs`](https://www.home-assistant.io/integrations/homeassistant/#allowlist_external_dirs) and at most 18 MB (OpenWA's request body limit is 25 MB, and base64 adds a third). `kind` (`image`, `video`, `audio`, `document`) defaults to the file's MIME type. Both actions return `message_id` when called with `response_variable`.

## Receiving

Every delivery fires `openwa_event` on the event bus:

```yaml
event_type: message.received     # OpenWA event name
session_id: 0b6f…           # session UUID
session_name: home-assistant
device_id: …
from: "4915112345678@c.us"       # message.* events only
timestamp: "2026-09-24T10:00:00.000Z"
data: { … }                      # OpenWA payload: id, from, to, body, type, isGroup, kind, contact, media, …
```

Subscribed events: `message.received`, `message.ack`, `session.status`, `session.qr`, `session.authenticated`, `session.disconnected`.

For automations built in the UI there is a device trigger **Message received** with an optional sender filter.

```yaml
triggers:
  - trigger: event
    event_type: openwa_event
    event_data:
      event_type: message.received
      from: "4915112345678@c.us"
actions:
  - action: persistent_notification.create
    data:
      message: "{{ trigger.event.data.data.body }}"
```

Deliveries are signed with HMAC-SHA256 (`X-OpenWA-Signature`) using a secret generated during setup. Unsigned or wrongly signed requests get a 401. Redeliveries with the same `idempotencyKey` fire only one event.

## Development

```sh
uv venv -p 3.14 .venv && uv pip install -p .venv -r requirements_test.txt
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

For checks against a real OpenWA instance, copy `.env.example` to `.env` (git-ignored) and fill in the URL, key and session id.

CI (GitLab) runs ruff, pytest, hassfest and an offline HACS structure check (`scripts/check_hacs.py`). `hacs/action` needs GitHub and cannot run here.
