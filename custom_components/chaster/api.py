from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession

from .const import API_BASE


class ChasterApiError(Exception):
    """Chaster API error."""


class ChasterApi:
    """Small async client for the Chaster Public API."""

    def __init__(self, session: ClientSession, token: str) -> None:
        self._session = session
        self._token = token

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make an authenticated request using the developer token."""
        if not path.startswith("/"):
            raise ChasterApiError("Chaster API paths must start with '/'")

        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("Accept", "application/json")
        headers["Authorization"] = f"Bearer {self._token}"
        url = f"{API_BASE}{path}"

        try:
            async with self._session.request(method.upper(), url, headers=headers, **kwargs) as response:
                if response.status >= 400:
                    raise ChasterApiError(
                        f"HTTP {response.status}: {(await response.text())[:1000]}"
                    )
                if response.status == 204:
                    return None
                return await response.json(content_type=None)
        except ClientError as err:
            raise ChasterApiError(str(err)) from err

    async def profile(self) -> Any:
        return await self.request("GET", "/auth/profile")

    async def locks(self, status: str | None = None) -> Any:
        params = {"status": status} if status else None
        return await self.request("GET", "/locks", params=params)

    async def lock(self, lock_id: str) -> Any:
        return await self.request("GET", f"/locks/{lock_id}")

    async def keyholder_locks(self, payload: dict[str, Any] | None = None) -> Any:
        return await self.request(
            "POST",
            "/keyholder/locks/search",
            json=payload or {"status": "locked", "page": 0, "limit": 50},
        )

    async def shared_locks(self, status: str = "active") -> Any:
        return await self.request("GET", "/shared-locks", params={"status": status})

    async def conversations(self) -> Any:
        return await self.request("GET", "/conversations")

    async def conversation(self, conversation_id: str) -> Any:
        return await self.request("GET", f"/conversations/{conversation_id}")

    async def send_message(self, conversation_id: str, payload: dict[str, Any]) -> Any:
        return await self.request("POST", f"/conversations/{conversation_id}", json=payload)

    async def create_conversation(self, payload: dict[str, Any]) -> Any:
        return await self.request("POST", "/conversations", json=payload)

    async def update_time(self, lock_id: str, seconds: int) -> Any:
        return await self.request(
            "POST", f"/locks/{lock_id}/update-time", json={"duration": seconds}
        )

    async def freeze(self, lock_id: str, frozen: bool) -> Any:
        return await self.request(
            "POST", f"/locks/{lock_id}/freeze", json={"isFrozen": frozen}
        )

    async def unlock(self, lock_id: str) -> Any:
        """Unlock a lock using Chaster's body-less POST endpoint."""
        return await self.request("POST", f"/locks/{lock_id}/unlock")

    async def emergency_unlock(self, lock_id: str) -> Any:
        return await self.request("POST", f"/locks/{lock_id}/emergency-unlock", json={})

    async def archive(self, lock_id: str, keyholder: bool = False) -> Any:
        suffix = "/archive/keyholder" if keyholder else "/archive"
        return await self.request("POST", f"/locks/{lock_id}{suffix}", json={})

    async def combination(self, lock_id: str) -> Any:
        return await self.request("GET", f"/locks/{lock_id}/combination")

    async def history(self, lock_id: str, payload: dict[str, Any] | None = None) -> Any:
        return await self.request("POST", f"/locks/{lock_id}/history", json=payload or {})

    async def settings(self, lock_id: str, payload: dict[str, Any]) -> Any:
        return await self.request("POST", f"/locks/{lock_id}/settings", json=payload)

    async def bondage_config(self, lock_id: str, payload: dict[str, Any]) -> Any:
        return await self.request("PATCH", f"/locks/{lock_id}/bondage-config", json=payload)

    async def permission_definitions(self) -> Any:
        return await self.request("GET", "/permissions/definitions")

    async def keyholder_notes(self, lock_id: str) -> Any:
        return await self.request("GET", f"/keyholder/notes/lock/{lock_id}")
