from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class LabControllerUnavailable(RuntimeError):
    pass


class LabClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.lab_monitor_token and self.settings.lab_operator_token)

    async def _request(self, method: str, path: str, *, operator: bool, json: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self.settings.lab_operator_token if operator else self.settings.lab_monitor_token
        if not token:
            raise LabControllerUnavailable("Lab controller credentials are not configured")
        try:
            async with httpx.AsyncClient(base_url=self.settings.lab_controller_url, timeout=30) as client:
                response = await client.request(method, path, headers={"X-Lab-Token": token}, json=json)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.json().get("detail", exc.response.text)
            raise LabControllerUnavailable(f"Lab controller rejected the request: {detail}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LabControllerUnavailable(f"Lab controller unavailable: {exc}") from exc

    async def create_run(self, scenario: str, ttl_seconds: int) -> dict[str, Any]:
        return await self._request("POST", "/v1/runs", operator=True, json={"scenario": scenario, "ttl_seconds": ttl_seconds})

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/runs/{run_id}", operator=True)

    async def cleanup(self, run_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/v1/runs/{run_id}/cleanup", operator=True)

    async def complete_run(self, run_id: str, action_id: str, verification: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/runs/{run_id}/complete",
            operator=True,
            json={
                "action_id": action_id,
                "verification_status": verification["status"],
                "verification": verification,
            },
        )

    async def inspect_resource(self, resource_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/resources/{resource_id}", operator=False)

    async def inspect_database_blocking(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/database/blocking", operator=False)

    async def execute(self, action_id: str, investigation_id: str, action_type: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/operations",
            operator=True,
            json={"action_id": action_id, "investigation_id": investigation_id, "action_type": action_type, "parameters": parameters},
        )
