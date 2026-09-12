from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ChasterCoordinator


class ChasterEntity(CoordinatorEntity):
    """Base entity for the Chaster account device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ChasterCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self):
        profile = self.coordinator.data.get("profile", {})
        username = profile.get("username") if isinstance(profile, dict) else None
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=f"Chaster - {username}" if username else "Chaster",
            manufacturer="Chaster",
            model="Chaster account",
        )
