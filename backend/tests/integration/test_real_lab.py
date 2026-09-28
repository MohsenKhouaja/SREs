import asyncio
import json
import os
from typing import Any

import httpx
import pytest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_groq,
    pytest.mark.skipif(os.getenv("RUN_REAL_LAB") != "1", reason="set RUN_REAL_LAB=1 for destructive real-lab acceptance"),
]

API_URL = os.getenv("REAL_LAB_API_URL", "http://localhost:8000").rstrip("/")
TERMINAL = {"completed", "completed_with_rejection", "inconclusive", "remediation_failed", "cancelled", "failed", "no_incident_observed"}


async def _wait_for(client: httpx.AsyncClient, investigation_id: str, wanted: set[str], timeout: float = 240) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    latest: dict[str, Any] = {}
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/investigation/{investigation_id}")
        response.raise_for_status()
        latest = response.json()
        if latest["status"] in wanted:
            return latest
        await asyncio.sleep(2)
    pytest.fail(f"Investigation {investigation_id} timed out in status {latest.get('status')}")


@pytest.mark.parametrize(
    ("scenario", "expected_action"),
    [
        ("redis-unavailable", "start_service"),
        ("database-blocking", "terminate_blocking_session"),
        ("release-regression", "rollback_release"),
    ],
)
async def test_real_groq_diagnoses_and_repairs_observed_fault(scenario: str, expected_action: str):
    async with httpx.AsyncClient(base_url=API_URL, timeout=30) as client:
        health = await client.get("/health")
        assert health.json() == {"status": "healthy"}
        launched = await client.post(
            "/lab/runs",
            json={"scenario": scenario, "auto_start_investigation": True, "ttl_seconds": 900},
        )
        launched.raise_for_status()
        identifiers = launched.json()
        investigation_id = identifiers["investigation_id"]
        run_id = identifiers["lab_run_id"]
        completed = False
        try:
            investigation = await _wait_for(client, investigation_id, {"awaiting_approval", *TERMINAL})
            assert investigation["status"] == "awaiting_approval", json.dumps(investigation, default=str)
            assert len(investigation["approvals"]) == 1
            approval = investigation["approvals"][0]
            assert approval["action_type"] == expected_action
            assert approval["supporting_finding_ids"]
            assert approval["supporting_observation_ids"]
            assert approval["parameters"]["resource_id"] == approval["target"]

            model_inputs = [
                run.get("input", {})
                for agent in investigation["agents"].values()
                for run in agent.get("llm_runs", [])
            ]
            assert model_inputs
            assert all(scenario not in json.dumps(model_input) for model_input in model_inputs)

            decision = await client.post(
                f"/investigation/{investigation_id}/approval/{approval['approval_id']}",
                json={"decision": "approve"},
            )
            decision.raise_for_status()
            investigation = await _wait_for(client, investigation_id, TERMINAL)
            assert investigation["status"] == "completed", json.dumps(investigation, default=str)
            execution = investigation["report_json"]["evidence"]["execution"]
            assert execution["operation"]["status"] == "succeeded"
            assert execution["verification"]["status"] == "verified"
            assert execution["recovery_origin"] == "agent_action"
            lab_run = await client.get(f"/lab/runs/{run_id}")
            lab_run.raise_for_status()
            assert lab_run.json()["status"] == "remediated"
            completed = True
        finally:
            if not completed:
                await client.post(f"/lab/runs/{run_id}/cleanup")
