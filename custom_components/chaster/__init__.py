from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers import config_validation as cv

from .api import ChasterApi, ChasterApiError
from .const import (
    CONF_ENABLE_KEYHOLDER,
    CONF_ENABLE_LOCK_ACTIONS,
    CONF_ENABLE_MESSAGING,
    CONF_ENABLE_SHARED_LOCKS,
    CONF_ROLE_MODE,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DOMAIN,
    PLATFORMS,
    ROLE_AUTO,
)
from .coordinator import ChasterCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _coordinators(hass: HomeAssistant) -> list[ChasterCoordinator]:
    """Return configured Chaster coordinators."""
    return [value for value in hass.data[DOMAIN].values() if isinstance(value, ChasterCoordinator)]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register Chaster services."""
    hass.data.setdefault(DOMAIN, {})

    async def _api_for_lock(lock_id: str):
        for coordinator in _coordinators(hass):
            if any(coordinator.lock_id(item) == lock_id for item in coordinator.all_locks):
                return coordinator.api, coordinator
        raise ValueError(f"Chaster lock {lock_id} is not known to this Home Assistant instance")

    async def api_request(call: ServiceCall) -> None:
        coordinators = _coordinators(hass)
        if not coordinators:
            raise ValueError("No Chaster account is configured")
        result = await coordinators[0].api.request(
            call.data["method"],
            call.data["path"],
            params=call.data.get("params"),
            json=call.data.get("body"),
        )
        hass.bus.async_fire(
            f"{DOMAIN}_api_response",
            {"method": call.data["method"], "path": call.data["path"], "result": result},
        )
        for coordinator in coordinators:
            await coordinator.async_request_refresh()

    async def lock_action(call: ServiceCall) -> None:
        api, coordinator = await _api_for_lock(call.data["lock_id"])
        if not coordinator.enable_lock_actions:
            raise ValueError("Chaster lock actions are disabled in integration options")
        path = call.data["path"].format(lock_id=call.data["lock_id"])
        result = await api.request(call.data.get("method", "POST"), path, json=call.data.get("body", {}))
        hass.bus.async_fire(
            f"{DOMAIN}_action",
            {"lock_id": call.data["lock_id"], "path": path, "result": result},
        )
        await coordinator.async_request_refresh()

    async def add_or_remove_time(call: ServiceCall) -> None:
        api, coordinator = await _api_for_lock(call.data["lock_id"])
        if not coordinator.enable_lock_actions:
            raise ValueError("Chaster lock actions are disabled in integration options")
        seconds = int(call.data["seconds"])
        result = await api.update_time(
            call.data["lock_id"], seconds if call.service == "add_time" else -seconds
        )
        hass.bus.async_fire(
            f"{DOMAIN}_action",
            {"lock_id": call.data["lock_id"], "action": call.service, "seconds": seconds, "result": result},
        )
        await coordinator.async_request_refresh()

    async def send_message(call: ServiceCall) -> None:
        coordinators = _coordinators(hass)
        if not coordinators:
            raise ValueError("No Chaster account is configured")
        result = await coordinators[0].api.request(
            "POST", call.data.get("path", "/conversations"), json=call.data["body"]
        )
        hass.bus.async_fire(f"{DOMAIN}_message", {"result": result})

    hass.services.async_register(
        DOMAIN,
        "api_request",
        api_request,
        schema=vol.Schema(
            {
                vol.Required("method"): vol.In(["GET", "POST", "PUT", "PATCH", "DELETE"]),
                vol.Required("path"): str,
                vol.Optional("params"): dict,
                vol.Optional("body"): dict,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "lock_action",
        lock_action,
        schema=vol.Schema(
            {
                vol.Required("lock_id"): str,
                vol.Required("path"): str,
                vol.Optional("method", default="POST"): vol.In(["POST", "PUT", "PATCH", "DELETE"]),
                vol.Optional("body"): dict,
            }
        ),
    )
    time_schema = vol.Schema(
        {
            vol.Required("lock_id"): str,
            vol.Required("seconds"): vol.All(vol.Coerce(int), vol.Range(min=1, max=31_536_000)),
        }
    )
    hass.services.async_register(DOMAIN, "add_time", add_or_remove_time, schema=time_schema)
    hass.services.async_register(DOMAIN, "remove_time", add_or_remove_time, schema=time_schema)
    hass.services.async_register(
        DOMAIN,
        "send_message",
        send_message,
        schema=vol.Schema({vol.Required("body"): dict, vol.Optional("path", default="/conversations"): str}),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Chaster config entry."""
    session = aiohttp_client.async_get_clientsession(hass)
    token = entry.data.get(CONF_TOKEN)
    if not isinstance(token, str) or not token.strip():
        raise ConfigEntryNotReady("No Chaster developer token is configured")

    api = ChasterApi(session, token=token.strip())
    settings = entry.options
    try:
        await api.profile()
    except ChasterApiError as err:
        message = str(err)
        if "HTTP 401" in message or "HTTP 403" in message:
            raise ConfigEntryAuthFailed("Chaster developer token is invalid or expired") from err
        raise ConfigEntryNotReady(f"Unable to connect to Chaster: {err}") from err

    coordinator = ChasterCoordinator(
        hass,
        api,
        settings.get(CONF_SCAN_INTERVAL, 60),
        role_mode=settings.get(CONF_ROLE_MODE, ROLE_AUTO),
        enable_keyholder=settings.get(CONF_ENABLE_KEYHOLDER, True),
        enable_shared=settings.get(CONF_ENABLE_SHARED_LOCKS, True),
        enable_messaging=settings.get(CONF_ENABLE_MESSAGING, True),
        enable_lock_actions=settings.get(CONF_ENABLE_LOCK_ACTIONS, True),
    )
    coordinator.config_entry = entry
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Chaster config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
