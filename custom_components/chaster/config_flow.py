"""Config flow for Chaster using a developer/API token."""

from __future__ import annotations

from typing import Any, override

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import aiohttp_client

from .api import ChasterApi, ChasterApiError
from .const import (
    CONF_ENABLE_KEYHOLDER,
    CONF_ENABLE_LOCK_ACTIONS,
    CONF_ENABLE_MESSAGING,
    CONF_ENABLE_SHARED_LOCKS,
    CONF_ROLE_MODE,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ROLE_AUTO,
    ROLE_BOTH,
    ROLE_KEYHOLDER,
    ROLE_WEARER,
)


class ChasterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Chaster developer-token authentication."""

    VERSION = 5

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for and validate a Chaster developer token."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        return await self._async_token_form(user_input, reauth_entry=None)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauthentication after a token expires or is revoked."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="reauth_failed")
        self._reauth_entry = entry
        return await self._async_token_form(None, reauth_entry=entry)

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Accept and validate a replacement developer token."""
        entry = getattr(self, "_reauth_entry", None)
        if entry is None:
            return self.async_abort(reason="reauth_failed")
        return await self._async_token_form(user_input, reauth_entry=entry)

    async def _async_token_form(self, user_input, reauth_entry):
        """Validate a token and either create or update the config entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = str(user_input.get(CONF_TOKEN, "")).strip()
            if not token:
                errors["base"] = "invalid_token"
            else:
                session = aiohttp_client.async_get_clientsession(self.hass)
                try:
                    await ChasterApi(session, token=token).profile()
                except ChasterApiError:
                    errors["base"] = "cannot_connect"
                else:
                    if reauth_entry is not None:
                        self.hass.config_entries.async_update_entry(
                            reauth_entry, data={**reauth_entry.data, CONF_TOKEN: token}
                        )
                        await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                        return self.async_abort(reason="reauth_successful")
                    return self.async_create_entry(title="Chaster", data={CONF_TOKEN: token})

        step_id = "reauth_confirm" if reauth_entry is not None else "user"
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            errors=errors,
            description_placeholders={"developers_url": "https://chaster.app/developers"},
        )

    @staticmethod
    @override
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return Chaster's role and feature settings flow."""
        return ChasterOptionsFlow(config_entry)


class ChasterOptionsFlow(config_entries.OptionsFlow):
    """Configure role-specific and optional Chaster features."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Handle integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        defaults = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SCAN_INTERVAL, default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                    vol.Optional(CONF_ROLE_MODE, default=defaults.get(CONF_ROLE_MODE, ROLE_AUTO)): vol.In([ROLE_AUTO, ROLE_WEARER, ROLE_KEYHOLDER, ROLE_BOTH]),
                    vol.Optional(CONF_ENABLE_KEYHOLDER, default=defaults.get(CONF_ENABLE_KEYHOLDER, True)): bool,
                    vol.Optional(CONF_ENABLE_SHARED_LOCKS, default=defaults.get(CONF_ENABLE_SHARED_LOCKS, True)): bool,
                    vol.Optional(CONF_ENABLE_MESSAGING, default=defaults.get(CONF_ENABLE_MESSAGING, True)): bool,
                    vol.Optional(CONF_ENABLE_LOCK_ACTIONS, default=defaults.get(CONF_ENABLE_LOCK_ACTIONS, True)): bool,
                }
            ),
        )
