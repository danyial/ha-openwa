"""Shared test data, shaped after real OpenWA 0.23.6 responses."""

URL = "http://openwa.test:2785"
API_KEY = "test-key"
SESSION_ID = "11111111-2222-4333-8444-555555555555"
SESSION_NAME = "home-assistant"
WEBHOOK_ID = "66666666-7777-4888-9999-000000000000"

SESSION_READY = {
    "id": SESSION_ID,
    "name": SESSION_NAME,
    "status": "ready",
    "phone": "4915100000000",
    "pushName": "HA",
    "connectedAt": "2026-09-24T08:00:00.000Z",
    "lastActive": "2026-09-24T10:00:00.000Z",
    "createdAt": "2026-09-01T00:00:00.000Z",
    "updatedAt": "2026-09-24T10:00:00.000Z",
    "lastError": None,
    "restriction": None,
    "engineLoaded": True,
}

QR_DATA_URL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42"
    "mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
