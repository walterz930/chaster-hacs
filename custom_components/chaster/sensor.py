from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory

from .coordinator import ChasterCoordinator
from .entity import ChasterEntity


def _id(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    for key in ("id", "_id", "lockId", "lock_id", "sessionId", "session_id"):
        value = item.get(key)
        if value is not None:
            return str(value)
    nested = item.get("lock")
    return _id(nested) if isinstance(nested, dict) else None


def _name(item: Any) -> str:
    if not isinstance(item, dict):
        return "Lock"
    return str(item.get("customWearerName") or item.get("name") or item.get("title") or _id(item) or "Lock")


def _number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except (TypeError, ValueError):
            return None
    return None


def _duration_seconds(value: Any) -> int | None:
    direct = _number(value)
    if direct is not None:
        return direct
    if isinstance(value, dict):
        for key in ("seconds", "totalSeconds", "remainingSeconds", "value", "duration", "total", "amount"):
            result = _duration_seconds(value.get(key))
            if result is not None:
                return result
    return None


def _date_seconds(value: Any) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int((parsed - datetime.now(timezone.utc)).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return None


def _remaining(item: Any) -> int | None:
    if not isinstance(item, dict):
        return None
    for key in ("remainingTime", "remainingSeconds", "remainingDuration", "timeRemaining", "durationRemaining", "remaining", "timerRemaining", "secondsRemaining"):
        result = _duration_seconds(item.get(key))
        if result is not None:
            return max(0, result)
    for key in ("endDate", "endAt", "unlockDate", "unlockAt", "maxLimitDate", "maximumDate"):
        result = _date_seconds(item.get(key))
        if result is not None:
            return result
    return None


def _permissions(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    for key in ("permissions", "lockPermissions", "resolvedPermissions", "permissionContract", "permission_contract"):
        if isinstance(item.get(key), dict):
            return item[key]
    return {}


def _attributes(lock: dict[str, Any], role: str | None = None, lock_type: str = "lock") -> dict[str, Any]:
    p = _permissions(lock)
    return {
        "lock_id": _id(lock), "role": role, "lock_type": lock_type, "status": lock.get("status"), "type": lock.get("type"),
        "remaining_seconds": _remaining(lock), "permissions": p,
        "can_add_time": p.get("add_time", p.get("addTime")), "can_remove_time": p.get("remove_time", p.get("removeTime")),
        "can_freeze": p.get("freeze", p.get("freeze_timer")), "can_unfreeze": p.get("unfreeze", p.get("unfreeze_timer")),
        "can_change_minimum_date": p.get("change_minimum_date"), "can_change_maximum_date": p.get("change_maximum_date"),
        "can_manage_extensions": p.get("manage_extensions"), "can_edit_safety": p.get("edit_bondage_safety_settings"),
        "wearer": lock.get("wearer"), "keyholder": lock.get("keyholder"),
        "start_date": lock.get("startDate", lock.get("startAt")), "end_date": lock.get("endDate", lock.get("endAt")),
        "minimum_date": lock.get("minLimitDate"), "maximum_date": lock.get("maxLimitDate"),
        "frozen": lock.get("frozen", lock.get("isFrozen")), "timer_visible": lock.get("timerVisibility"),
        "history_time_visible": lock.get("timeLogsVisibility"), "extensions": lock.get("extensions"),
    }


def _keyholder_items(coordinator: ChasterCoordinator) -> list[dict[str, Any]]:
    data = coordinator.data if isinstance(coordinator.data, dict) else {}
    keyholder = data.get("keyholder")
    if not isinstance(keyholder, dict):
        return []
    value = keyholder.get("items") or keyholder.get("locks") or keyholder.get("results") or keyholder.get("data") or []
    if isinstance(value, dict):
        value = list(value.values())
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _nested_lock(item: dict[str, Any]) -> dict[str, Any]:
    nested = item.get("lock")
    return nested if isinstance(nested, dict) else item


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: ChasterCoordinator = hass.data[entry.domain][entry.entry_id]
    entities = [ChasterAccountSensor(coordinator), ChasterCurrentLockSensor(coordinator), ChasterHistorySensor(coordinator)]
    for item in coordinator.data.get("locks", []):
        if _id(item):
            entities.append(ChasterLockSensor(coordinator, item, "wearer"))
    for item in _keyholder_items(coordinator):
        lock = _nested_lock(item)
        if _id(lock):
            entities.append(ChasterLockSensor(coordinator, lock, "keyholder"))
    for item in coordinator.data.get("shared_locks", []):
        if _id(item):
            entities.append(ChasterSharedLockSensor(coordinator, item))
    async_add_entities(entities)


class ChasterAccountSensor(ChasterEntity, SensorEntity):
    _attr_icon = "mdi:account-lock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_account"
        self._attr_name = "Chaster account"

    @property
    def native_value(self):
        return self.coordinator.data.get("profile", {}).get("username", "Connected")

    @property
    def extra_state_attributes(self):
        profile = dict(self.coordinator.data.get("profile", {}))
        profile.pop("token", None)
        profile.pop("accessToken", None)
        return {
            "role_mode": self.coordinator.role_mode,
            "detected_role": self.coordinator.detected_role,
            "detected_roles": self.coordinator.data.get("detected_roles", []),
            "available_lock_types": [*(["wearer"] if "wearer" in self.coordinator.data.get("detected_roles", []) else []), *(["keyholder"] if "keyholder" in self.coordinator.data.get("detected_roles", []) else []), *(["shared"] if self.coordinator.data.get("shared_locks") else [])],
            "profile": profile,
            "keyholder_enabled": self.coordinator.enable_keyholder,
            "shared_locks_enabled": self.coordinator.enable_shared,
            "messaging_enabled": self.coordinator.enable_messaging,
        }


class ChasterCurrentLockSensor(ChasterEntity, SensorEntity):
    _attr_icon = "mdi:lock-clock"
    _attr_native_unit_of_measurement = "s"
    _attr_device_class = "duration"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_current_lock"
        self._attr_name = "Current lock"

    @property
    def _lock(self):
        lock = self.coordinator.data.get("current_lock")
        if isinstance(lock, dict) and _id(lock):
            return lock
        active = [x for x in self.coordinator.all_locks if self.coordinator.is_active(x)]
        return max(active, key=lambda x: str(x.get("startDate") or x.get("startAt") or ""), default={})

    @property
    def _role(self):
        lock_id = _id(self._lock)
        if lock_id and any(_id(x) == lock_id for x in self.coordinator.data.get("locks", [])):
            return "wearer"
        return "keyholder" if lock_id else "none"

    @property
    def native_value(self):
        return _remaining(self._lock) if self._lock else None

    @property
    def extra_state_attributes(self):
        lock = self._lock
        return _attributes(lock, self._role, "active_lock") if lock else {"role": "none", "lock_type": "active_lock", "status": "no_active_lock"}


class ChasterHistorySensor(ChasterEntity, SensorEntity):
    _attr_icon = "mdi:history"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_history_sensor"
        self._attr_name = "Current lock history"

    @property
    def native_value(self):
        history = self.coordinator.data.get("history", [])
        return len(history) if isinstance(history, list) else len(self.coordinator._dict_list(history))

    @property
    def extra_state_attributes(self):
        history = self.coordinator.data.get("history", [])
        if not isinstance(history, list):
            history = self.coordinator._dict_list(history)
        lock = self.coordinator.current_lock or {}
        role = "wearer" if any(_id(x) == _id(lock) for x in self.coordinator.data.get("locks", [])) else "keyholder"
        return {"lock_id": _id(lock), "role": role if _id(lock) else "none", "lock_type": "history", "entries": history[-50:]}


class ChasterLockSensor(ChasterEntity, SensorEntity):
    _attr_icon = "mdi:lock-clock"
    _attr_native_unit_of_measurement = "s"
    _attr_device_class = "duration"

    def __init__(self, coordinator, initial, role):
        super().__init__(coordinator)
        self.lock_id = _id(initial)
        self.role = role
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_lock_{self.lock_id}_{role}"
        self._attr_name = f"{'My' if role == 'wearer' else 'Keyholder'} lock - {_name(initial)}"

    @property
    def _lock(self):
        if self.role == "wearer":
            return next((x for x in self.coordinator.data.get("locks", []) if _id(x) == self.lock_id), {})
        for item in _keyholder_items(self.coordinator):
            lock = _nested_lock(item)
            if _id(lock) == self.lock_id:
                return lock
        return {}

    @property
    def native_value(self):
        return _remaining(self._lock) if self._lock else None

    @property
    def extra_state_attributes(self):
        return _attributes(self._lock, self.role, "active_lock")


class ChasterSharedLockSensor(ChasterEntity, SensorEntity):
    _attr_icon = "mdi:account-multiple-lock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, initial):
        super().__init__(coordinator)
        self.shared_id = _id(initial)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_shared_{self.shared_id}"
        self._attr_name = f"Shared lock - {_name(initial)}"

    @property
    def _lock(self):
        return next((x for x in self.coordinator.data.get("shared_locks", []) if _id(x) == self.shared_id), {})

    @property
    def native_value(self):
        lock = self._lock
        return lock.get("status", "unknown") if lock else "unknown"

    @property
    def extra_state_attributes(self):
        lock = self._lock
        return {"lock_type": "shared", "role": "owner", "shared_lock_id": self.shared_id, **{k: v for k, v in lock.items() if k not in ("token", "accessToken", "secret")}}
