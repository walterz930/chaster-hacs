from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity

from .coordinator import ChasterCoordinator
from .entity import ChasterEntity


class _CurrentLockBinary(ChasterEntity, BinarySensorEntity):
    def __init__(self, coordinator, suffix, name, icon):
        super().__init__(coordinator)
        self._suffix = suffix
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{suffix}"

    @property
    def _lock(self):
        return self.coordinator.current_lock or {}

    @property
    def extra_state_attributes(self):
        lock = self._lock
        return {
            "lock_id": self.coordinator.lock_id(lock),
            "status": lock.get("status"),
            "type": lock.get("type"),
        }


class ChasterLockedBinary(_CurrentLockBinary):
    def __init__(self, coordinator):
        super().__init__(coordinator, "locked", "Chaster locked", "mdi:lock")

    @property
    def is_on(self):
        return self.coordinator.is_active(self._lock)


class ChasterFrozenBinary(_CurrentLockBinary):
    def __init__(self, coordinator):
        super().__init__(coordinator, "frozen", "Chaster frozen", "mdi:snowflake")

    @property
    def is_on(self):
        lock = self._lock
        return bool(lock.get("frozen", lock.get("isFrozen", False)))


class ChasterTestBinary(_CurrentLockBinary):
    def __init__(self, coordinator):
        super().__init__(coordinator, "test_lock", "Chaster test lock", "mdi:flask-outline")

    @property
    def is_on(self):
        lock = self._lock
        return bool(lock.get("isTestLock", lock.get("test", lock.get("isTest", lock.get("testLock", False)))))


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: ChasterCoordinator = hass.data[entry.domain][entry.entry_id]
    async_add_entities([
        ChasterLockedBinary(coordinator),
        ChasterFrozenBinary(coordinator),
        ChasterTestBinary(coordinator),
    ])
