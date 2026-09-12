from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity

from .api import ChasterApiError
from .coordinator import ChasterCoordinator
from .entity import ChasterEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: ChasterCoordinator = hass.data[entry.domain][entry.entry_id]
    entities = [ChasterActionButton(coordinator, "refresh", "Refresh Chaster", "mdi:refresh", None)]
    for role, label in (("wearer", "My lock"), ("keyholder", "Keyholder")):
        for action, suffix, icon in (
            ("history", "Refresh history", "mdi:history"),
            ("freeze", "Freeze", "mdi:snowflake"),
            ("unfreeze", "Unfreeze", "mdi:snowflake-off"),
            ("unlock", "Unlock", "mdi:lock-open"),
            ("emergency_unlock", "Emergency unlock", "mdi:alert-octagon"),
            ("archive", "Archive", "mdi:archive"),
        ):
            entities.append(ChasterActionButton(coordinator, action, f"{label} - {suffix}", icon, role))
    async_add_entities(entities)


class ChasterActionButton(ChasterEntity, ButtonEntity):
    _attr_entity_category = None

    def __init__(self, coordinator, action: str, name: str, icon: str, role: str | None) -> None:
        super().__init__(coordinator)
        self._action = action
        self._role = role
        self._attr_name = name
        self._attr_icon = icon
        role_id = role or "general"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{role_id}_{action}"

    @staticmethod
    def _status(lock: dict[str, Any] | None) -> str:
        if not isinstance(lock, dict):
            return ""
        return str(lock.get("status", lock.get("state", ""))).strip().lower().replace("_", "-").replace(" ", "-")

    @staticmethod
    def _terminal(lock: dict[str, Any]) -> bool:
        return ChasterActionButton._status(lock) in {
            "unlocked", "archived", "deserted", "ended", "completed", "cancelled", "canceled",
        }

    def _wearer_locks(self) -> list[dict[str, Any]]:
        data = self.coordinator.data if isinstance(self.coordinator.data, dict) else {}
        value = data.get("locks", [])
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            for key in ("items", "results", "data", "locks", "sessions", "entries"):
                items = value.get(key)
                if isinstance(items, list):
                    return [item for item in items if isinstance(item, dict)]
                if isinstance(items, dict):
                    return [item for item in items.values() if isinstance(item, dict)]
        return []

    def _keyholder_locks(self) -> list[dict[str, Any]]:
        data = self.coordinator.data if isinstance(self.coordinator.data, dict) else {}
        keyholder = data.get("keyholder")
        if not isinstance(keyholder, dict):
            return []
        value = keyholder.get("items") or keyholder.get("locks") or keyholder.get("results") or keyholder.get("data") or []
        if isinstance(value, dict):
            value = list(value.values())
        result = []
        for item in value if isinstance(value, list) else []:
            if not isinstance(item, dict):
                continue
            lock = item.get("lock") if isinstance(item.get("lock"), dict) else item
            if isinstance(lock, dict):
                result.append(lock)
        return result

    def _candidate_locks(self) -> list[dict[str, Any]]:
        if self._role == "wearer":
            locks = self._wearer_locks()
        elif self._role == "keyholder":
            locks = self._keyholder_locks()
        else:
            locks = []
        candidates = []
        for lock in locks:
            if not self.coordinator.lock_id(lock):
                continue
            if self._terminal(lock) and not (self._action == "archive" and self._status(lock) == "unlocked"):
                continue
            candidates.append(lock)
        return candidates

    def _lock_sort_key(self, lock: dict[str, Any]) -> str:
        return str(lock.get("startDate") or lock.get("startAt") or lock.get("createdAt") or "")

    @property
    def _lock(self) -> dict[str, Any] | None:
        candidates = self._candidate_locks()
        if self._action == "archive":
            return max(candidates, key=self._lock_sort_key, default=None)
        return max([lock for lock in candidates if self.coordinator.is_active(lock)], key=self._lock_sort_key, default=None)

    def _mode_allows_action(self, lock: dict[str, Any] | None) -> bool:
        status = self._status(lock)
        if not status:
            return False
        if self._action == "freeze":
            return status in {"locked", "locking", "running", "active", "started", "start", "in-progress", "inprogress"}
        if self._action == "unfreeze":
            return status in {"frozen", "paused"}
        if self._action == "unlock":
            return status in {"locked", "locking", "running", "active", "started", "start", "frozen", "paused", "in-progress", "inprogress", "ready-to-unlock", "readyforunlock"}
        if self._action == "emergency_unlock":
            return self._role == "wearer" and status in {"locked", "locking", "running", "active", "started", "start", "frozen", "paused", "in-progress", "inprogress"}
        if self._action == "archive":
            return status in {"unlocked", "ready-to-archive"}
        if self._action == "history":
            return self.coordinator.is_active(lock)
        return True

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if self._action == "refresh":
            return True
        if not self.coordinator.enable_lock_actions:
            return False
        lock = self._lock
        return bool(lock and self.coordinator.lock_id(lock) and self._mode_allows_action(lock))

    async def async_press(self) -> None:
        if self._action == "refresh":
            await self.coordinator.async_request_refresh()
            return
        if not self.coordinator.enable_lock_actions:
            return
        lock = self._lock
        lock_id = self.coordinator.lock_id(lock) if lock else None
        if not lock_id or not self._mode_allows_action(lock):
            await self.coordinator.async_request_refresh()
            return
        if self._action != "history":
            try:
                fresh = await self.coordinator.api.lock(lock_id)
            except ChasterApiError:
                await self.coordinator.async_request_refresh()
                return
            if not isinstance(fresh, dict) or self.coordinator.lock_id(fresh) != lock_id:
                await self.coordinator.async_request_refresh()
                return
            lock = fresh
            if not self._mode_allows_action(lock):
                await self.coordinator.async_request_refresh()
                return
        if self._action == "history":
            result = await self.coordinator.api.history(lock_id)
            self.hass.bus.async_fire("chaster_history", {"lock_id": lock_id, "role": self._role, "history": result})
        elif self._action == "freeze":
            await self.coordinator.api.freeze(lock_id, True)
        elif self._action == "unfreeze":
            await self.coordinator.api.freeze(lock_id, False)
        elif self._action == "unlock":
            await self.coordinator.api.unlock(lock_id)
        elif self._action == "emergency_unlock":
            if self._role != "wearer":
                await self.coordinator.async_request_refresh()
                return
            await self.coordinator.api.emergency_unlock(lock_id)
        elif self._action == "archive":
            await self.coordinator.api.archive(lock_id, keyholder=self._role == "keyholder")
        await self.coordinator.async_request_refresh()
