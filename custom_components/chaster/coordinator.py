from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ChasterApi, ChasterApiError
from .const import DEFAULT_SCAN_INTERVAL, ROLE_AUTO, ROLE_BOTH, ROLE_KEYHOLDER, ROLE_WEARER

_LOGGER = logging.getLogger(__name__)


class ChasterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate Chaster data, current lock state and history."""

    def __init__(self, hass: HomeAssistant, api: ChasterApi, interval: int = DEFAULT_SCAN_INTERVAL, role_mode: str = ROLE_AUTO, enable_keyholder: bool = True, enable_shared: bool = True, enable_messaging: bool = True, enable_lock_actions: bool = True) -> None:
        self.api = api
        self.role_mode = role_mode
        self.enable_keyholder = enable_keyholder
        self.enable_shared = enable_shared
        self.enable_messaging = enable_messaging
        self.enable_lock_actions = enable_lock_actions
        super().__init__(hass, logger=_LOGGER, name="Chaster", update_interval=timedelta(seconds=interval))

    @staticmethod
    def _dict_list(value: Any) -> list[dict[str, Any]]:
        """Normalize common Chaster collection response shapes."""
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            for key in ("items", "results", "data", "locks", "sessions", "entries"):
                items = value.get(key)
                if isinstance(items, list):
                    return [item for item in items if isinstance(item, dict)]
                if isinstance(items, dict):
                    return [item for item in items.values() if isinstance(item, dict)]
            if value and all(isinstance(item, dict) for item in value.values()):
                return list(value.values())
        return []

    @staticmethod
    def lock_id(item: Any) -> str | None:
        if not isinstance(item, dict):
            return None
        for key in ("id", "_id", "lockId", "lock_id", "sessionId", "session_id"):
            if item.get(key) is not None:
                return str(item[key])
        nested = item.get("lock")
        if isinstance(nested, dict):
            return ChasterCoordinator.lock_id(nested)
        return None

    @staticmethod
    def _date(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def is_active(lock: Any) -> bool:
        if not isinstance(lock, dict):
            return False
        status = str(lock.get("status", lock.get("state", ""))).strip().lower().replace("_", "-").replace(" ", "-")
        if status in {"unlocked", "archived", "deserted", "ended", "completed", "cancelled", "canceled"}:
            return False
        if status in {"locked", "locking", "running", "active", "started", "start", "frozen", "paused", "in-progress", "inprogress", "ready-to-unlock", "readyforunlock"}:
            return True
        start = ChasterCoordinator._date(lock.get("startDate") or lock.get("startAt") or lock.get("startedAt"))
        end = ChasterCoordinator._date(lock.get("endDate") or lock.get("endAt") or lock.get("unlockDate") or lock.get("unlockAt") or lock.get("maxLimitDate"))
        now = datetime.now(timezone.utc)
        return bool((start is None or start <= now) and end is not None and end > now)

    @property
    def detected_role(self) -> str:
        data = self.data if isinstance(self.data, dict) else {}
        roles = data.get("detected_roles") or []
        return "unknown" if not roles else ROLE_BOTH if len(roles) == 2 else roles[0]

    @property
    def all_locks(self) -> list[dict[str, Any]]:
        data = self.data if isinstance(self.data, dict) else {}
        locks = self._dict_list(data.get("locks"))
        keyholder = data.get("keyholder")
        items: Any = []
        if isinstance(keyholder, dict):
            items = keyholder.get("items") or keyholder.get("locks") or keyholder.get("results") or keyholder.get("data") or []
        if isinstance(items, dict):
            items = list(items.values())
        ids = {self.lock_id(x) for x in locks if self.lock_id(x)}
        for item in items if isinstance(items, list) else []:
            lock = item.get("lock") if isinstance(item, dict) and isinstance(item.get("lock"), dict) else item
            if isinstance(lock, dict) and self.lock_id(lock) and self.lock_id(lock) not in ids:
                locks.append(lock)
                ids.add(self.lock_id(lock))
        return locks

    @property
    def current_lock(self) -> dict[str, Any] | None:
        data = self.data if isinstance(self.data, dict) else {}
        lock = data.get("current_lock")
        if isinstance(lock, dict) and self.lock_id(lock):
            return lock
        active = [x for x in self.all_locks if self.is_active(x)]
        return max(active, key=lambda x: str(x.get("startDate") or x.get("startAt") or x.get("createdAt") or ""), default=None)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            profile = await self.api.profile()
            if not isinstance(profile, dict):
                profile = {}

            requested_wearer = self.role_mode in (ROLE_AUTO, ROLE_WEARER, ROLE_BOTH)
            requested_keyholder = self.role_mode in (ROLE_AUTO, ROLE_KEYHOLDER, ROLE_BOTH)
            old_data = self.data if isinstance(self.data, dict) else {}

            locks: list[dict[str, Any]] = []
            wearer_available = False
            if requested_wearer:
                try:
                    locks = self._dict_list(await self.api.locks())
                    wearer_available = True
                except ChasterApiError as err:
                    _LOGGER.debug("Wearer scope unavailable: %s", err)
                    if self.role_mode == ROLE_WEARER:
                        raise

            old_locks = self._dict_list(old_data.get("locks"))
            current_ids = {self.lock_id(x) for x in locks if self.lock_id(x)}
            for item in old_locks:
                item_id = self.lock_id(item)
                if item_id and item_id not in current_ids:
                    locks.append(item)
                    current_ids.add(item_id)

            shared: list[dict[str, Any]] = []
            if self.enable_shared and requested_keyholder:
                try:
                    shared = self._dict_list(await self.api.shared_locks("active"))
                except ChasterApiError as err:
                    _LOGGER.debug("Shared-lock scope unavailable: %s", err)
                    shared = self._dict_list(old_data.get("shared_locks"))

            keyholder: dict[str, Any] = {}
            keyholder_available = False
            if self.enable_keyholder and requested_keyholder:
                try:
                    result = await self.api.keyholder_locks()
                    keyholder = result if isinstance(result, dict) else {"items": self._dict_list(result)}
                    keyholder_available = True
                except ChasterApiError as err:
                    _LOGGER.debug("Keyholder scope unavailable: %s", err)
                    keyholder = old_data.get("keyholder") if isinstance(old_data.get("keyholder"), dict) else {}
                    if self.role_mode == ROLE_KEYHOLDER:
                        raise

            conversations: list[dict[str, Any]] = []
            if self.enable_messaging:
                try:
                    conversations = self._dict_list(await self.api.conversations())
                except ChasterApiError as err:
                    _LOGGER.debug("Messaging scope unavailable: %s", err)
                    conversations = self._dict_list(old_data.get("conversations"))

            old_current = old_data.get("current_lock")
            combined = locks.copy()
            if isinstance(keyholder, dict):
                combined.extend(self._dict_list(keyholder.get("items") or keyholder.get("locks") or keyholder.get("results") or keyholder.get("data")))
            active = [x for x in combined if self.is_active(x)]
            current = max(active, key=lambda x: str(x.get("startDate") or x.get("startAt") or x.get("createdAt") or ""), default=None)
            if current is None and isinstance(old_current, dict) and self.lock_id(old_current):
                current = old_current

            if current and self.lock_id(current):
                try:
                    detail = await self.api.lock(self.lock_id(current))
                    if isinstance(detail, dict) and self.lock_id(detail):
                        current = detail
                        for i, item in enumerate(locks):
                            if self.lock_id(item) == self.lock_id(current):
                                locks[i] = detail
                                break
                except ChasterApiError as err:
                    _LOGGER.debug("Unable to refresh current lock details: %s", err)

            history: list[dict[str, Any]] = []
            if current and self.lock_id(current):
                try:
                    history = self._dict_list(await self.api.history(self.lock_id(current)))
                except ChasterApiError as err:
                    _LOGGER.debug("Unable to retrieve current lock history: %s", err)
                    history = self._dict_list(old_data.get("history"))

            detected_roles = ([ROLE_WEARER] if wearer_available else []) + ([ROLE_KEYHOLDER] if keyholder_available else [])
            return {
                "profile": profile,
                "locks": locks,
                "current_lock": current,
                "history": history,
                "shared_locks": shared,
                "keyholder": keyholder,
                "conversations": conversations,
                "role_mode": self.role_mode,
                "detected_roles": detected_roles,
                "detected_role": ROLE_BOTH if len(detected_roles) == 2 else detected_roles[0] if detected_roles else "unknown",
            }
        except ChasterApiError as err:
            raise UpdateFailed(str(err)) from err
