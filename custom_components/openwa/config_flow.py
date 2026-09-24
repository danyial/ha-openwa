"""Config flow for OpenWA."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components import webhook
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import CannotConnect, InvalidAuth, OpenWAClient, OpenWAError
from .const import (
    CONF_DEFAULT_CHAT_IDS,
    CONF_SCAN_INTERVAL,
    CONF_SESSIONS,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    CONF_WEBHOOK_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    WEBHOOK_EVENTS,
)
from .helpers import normalize_chat_id

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class OpenWAConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up an OpenWA instance: server, sessions, webhook."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self._url = ""
        self._api_key = ""
        self._available: dict[str, str] = {}
        self._sessions: dict[str, str] = {}

    def _client(self, api_key: str | None = None) -> OpenWAClient:
        return OpenWAClient(
            async_get_clientsession(self.hass), self._url, api_key or self._api_key
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for server URL and API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._url = user_input[CONF_URL].strip().rstrip("/")
            self._api_key = user_input[CONF_API_KEY].strip()
            await self.async_set_unique_id(self._url.lower())
            self._abort_if_unique_id_configured()
            try:
                client = self._client()
                await client.validate()
                sessions = await client.list_sessions()
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except OpenWAError:
                _LOGGER.exception("Unexpected OpenWA response")
                errors["base"] = "unknown"
            else:
                self._available = {s["id"]: s["name"] for s in sessions}
                if not self._available:
                    errors["base"] = "no_sessions"
                else:
                    return await self.async_step_sessions()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_sessions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the sessions to add (stored by UUID)."""
        if user_input is not None:
            self._sessions = {
                sid: self._available[sid] for sid in user_input[CONF_SESSIONS]
            }
            return await self.async_step_webhook()
        options = [
            SelectOptionDict(value=sid, label=name)
            for sid, name in sorted(self._available.items(), key=lambda i: i[1])
        ]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SESSIONS, default=[options[0]["value"]]
                ): SelectSelector(SelectSelectorConfig(options=options, multiple=True))
            }
        )
        return self.async_show_form(step_id="sessions", data_schema=schema)

    async def async_step_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create OpenWA webhooks pointing at HA and send a test delivery."""
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None:
            base_url = user_input[CONF_WEBHOOK_URL].strip().rstrip("/")
            webhook_id = webhook.async_generate_id()
            secret = secrets.token_hex(32)
            target = f"{base_url}{webhook.async_generate_path(webhook_id)}"
            error = await self._create_and_test_webhooks(target, secret)
            if error is None:
                return self.async_create_entry(
                    title=self._url.split("://", 1)[-1],
                    data={
                        CONF_URL: self._url,
                        CONF_API_KEY: self._api_key,
                        CONF_SESSIONS: self._sessions,
                        CONF_WEBHOOK_ID: webhook_id,
                        CONF_WEBHOOK_SECRET: secret,
                        CONF_WEBHOOK_URL: base_url,
                    },
                )
            errors["base"] = "webhook_test_failed"
            placeholders["error"] = error

        try:
            default = get_url(self.hass, prefer_external=True, allow_cloud=False)
        except NoURLAvailableError:
            default = ""
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_WEBHOOK_URL,
                    default=(user_input or {}).get(CONF_WEBHOOK_URL, default),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
            }
        )
        return self.async_show_form(
            step_id="webhook",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _create_and_test_webhooks(self, target: str, secret: str) -> str | None:
        """Create one webhook per session and test it. Roll back on failure."""
        client = self._client()
        created: list[tuple[str, str]] = []
        error: str | None = None
        try:
            for sid, name in self._sessions.items():
                hook = await client.create_webhook(sid, target, WEBHOOK_EVENTS, secret)
                created.append((sid, hook["id"]))
                result = await client.test_webhook(sid, hook["id"])
                if not result.get("success"):
                    detail = result.get("error") or f"HTTP {result.get('statusCode')}"
                    error = f"{name}: {detail}"
                    break
        except OpenWAError as err:
            error = str(err)
        if error is not None:
            for sid, hook_id in created:
                try:
                    await client.delete_webhook(sid, hook_id)
                except OpenWAError:
                    _LOGGER.warning("Could not roll back webhook %s", hook_id)
        return error

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth when the API key was rejected."""
        self._url = entry_data[CONF_URL]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            try:
                await self._client(api_key).validate()
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates={CONF_API_KEY: api_key}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OpenWAOptionsFlow:
        """Return the options flow."""
        return OpenWAOptionsFlow()


class OpenWAOptionsFlow(OptionsFlow):
    """Default chat per session and polling interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit options."""
        sessions: dict[str, str] = self.config_entry.data[CONF_SESSIONS]
        current: dict[str, str] = self.config_entry.options.get(
            CONF_DEFAULT_CHAT_IDS, {}
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            chats: dict[str, str] = {}
            for sid, name in sessions.items():
                raw = (user_input.get(name) or "").strip()
                if not raw:
                    continue
                try:
                    chats[sid] = normalize_chat_id(raw, self.hass.config.country)
                except ValueError:
                    errors[name] = "invalid_chat_id"
            if not errors:
                return self.async_create_entry(
                    data={
                        CONF_DEFAULT_CHAT_IDS: chats,
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                    }
                )

        fields: dict[Any, Any] = {}
        for sid, name in sessions.items():
            fields[
                vol.Optional(name, description={"suggested_value": current.get(sid)})
            ] = str
        fields[
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=self.config_entry.options.get(
                    CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
                ),
            )
        ] = vol.All(vol.Coerce(int), vol.Range(min=15, max=3600))
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(fields), errors=errors
        )
