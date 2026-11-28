"""Read-only IMPACT Web and CMMS clients (TWIN_SYNC_TOKEN) plus isolated delegated raise helper (TWIN_RAISE_TOKEN)."""

from __future__ import annotations

from typing import Any

import httpx


class ImpactWebClient:
    """Client for IMPACT Web public API. Sync methods use ONLY TWIN_SYNC_TOKEN (read-only)."""

    def __init__(
        self,
        *,
        base_url: str,
        sync_token: str,
        raise_token: str = "",
        http_client: httpx.Client | None = None,
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._sync_token = sync_token
        self._raise_token = raise_token
        self._client = http_client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def _sync_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._sync_token}"}

    def _raise_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._raise_token}"}

    def get_exercise(self, exercise_id: str) -> dict[str, Any]:
        r = self._client.get(f"/api/v1/exercises/{exercise_id}", headers=self._sync_headers())
        r.raise_for_status()
        return r.json()

    def list_work_requests(self, exercise_id: str) -> list[dict[str, Any]]:
        r = self._client.get(
            "/api/v1/work-requests",
            params={"exercise_id": exercise_id},
            headers=self._sync_headers(),
        )
        r.raise_for_status()
        return r.json()

    def get_changes(self, exercise_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        r = self._client.get(
            "/api/v1/changes",
            params={"exercise_id": exercise_id, "after_seq": after_seq},
            headers=self._sync_headers(),
        )
        r.raise_for_status()
        return r.json()

    def get_freeze_items(self, freeze_id: str) -> list[dict[str, Any]]:
        r = self._client.get(f"/api/v1/freezes/{freeze_id}/items", headers=self._sync_headers())
        r.raise_for_status()
        return r.json()

    def list_change_requests(self, exercise_id: str) -> list[dict[str, Any]]:
        r = self._client.get(
            "/api/v1/change-requests",
            params={"exercise_id": exercise_id},
            headers=self._sync_headers(),
        )
        r.raise_for_status()
        return r.json()

    def list_memberships(self, exercise_id: str) -> list[dict[str, Any]]:
        r = self._client.get(f"/api/v1/exercises/{exercise_id}/memberships", headers=self._sync_headers())
        r.raise_for_status()
        return r.json()

    def verify_user_token(self, bearer_token: str) -> dict[str, Any] | None:
        """Ask IMPACT Web to verify a caller's user bearer token via GET /api/v1/auth/me."""
        r = self._client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {bearer_token}"})
        if r.status_code != 200:
            return None
        return r.json()

    def login_user(self, email: str, password: str) -> dict[str, Any] | None:
        """Forward local-mode credentials to IMPACT Web /api/v1/auth/login so IMPACT Web stays identity authority."""
        r = self._client.post("/api/v1/auth/login", json={"email": email, "password": password})
        if r.status_code != 200:
            return None
        return r.json()

    def raise_twin_change_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Delegated write-through call (design.md section 5.8). Uses ONLY TWIN_RAISE_TOKEN."""
        if not self._raise_token:
            raise RuntimeError("TWIN_RAISE_TOKEN is not configured")
        r = self._client.post("/api/v1/twin/change-requests", json=payload, headers=self._raise_headers())
        r.raise_for_status()
        return r.json()


class CmmsClient:
    """Read-only client for the CMMS / TLM equipment master module."""

    def __init__(
        self,
        *,
        base_url: str,
        sync_token: str,
        http_client: httpx.Client | None = None,
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._sync_token = sync_token
        self._client = http_client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._sync_token}"}

    def list_equipment(self) -> list[dict[str, Any]]:
        r = self._client.get("/api/v1/cmms/equipment", headers=self._headers())
        r.raise_for_status()
        return r.json()

    def list_functional_locations(self) -> list[dict[str, Any]]:
        r = self._client.get("/api/v1/cmms/functional-locations", headers=self._headers())
        r.raise_for_status()
        return r.json()
