from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
import math
from typing import Any

import httpx

from .config import Settings
from .lab_client import LabClient
from .models import utc_iso


async def _probe(client: httpx.AsyncClient, service: str, settings: Settings) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    if service == "api-server":
        cases = [(f"{settings.sample_api_url}/api/users", "users"), (f"{settings.sample_api_url}/api/products", "products")]
        for url, field in cases:
            started = time.monotonic()
            try:
                response = await client.get(url, timeout=4)
                elapsed = time.monotonic() - started
                body = response.json()
                passed = response.is_success and isinstance(body.get(field), list) and elapsed < 2
                observations.append({"service": service, "path": httpx.URL(url).path, "status_code": response.status_code, "duration_seconds": round(elapsed, 3), "passed": passed, "observed_at": utc_iso()})
            except (httpx.HTTPError, ValueError) as exc:
                observations.append({"service": service, "path": httpx.URL(url).path, "passed": False, "error": str(exc), "observed_at": utc_iso()})
    elif service == "payment-service":
        marker = f"verification-{uuid.uuid4().hex[:10]}"
        started = time.monotonic()
        try:
            created = await client.post(f"{settings.sample_payment_url}/api/payments", json={"amount": 0.01, "currency": marker}, timeout=4)
            creation = created.json()
            payment_id = creation.get("payment_id")
            fetched = await client.get(f"{settings.sample_payment_url}/api/payments/{payment_id}", timeout=4) if payment_id else None
            elapsed = time.monotonic() - started
            body = fetched.json() if fetched else {}
            passed = bool(created.is_success and payment_id and fetched and fetched.is_success and body.get("payment_id") == payment_id and body.get("status") == "processed" and elapsed < 2)
            observations.append({"service": service, "path": "/api/payments -> /api/payments/{id}", "status_code": fetched.status_code if fetched else created.status_code, "duration_seconds": round(elapsed, 3), "payment_id": payment_id, "passed": passed, "observed_at": utc_iso()})
        except (httpx.HTTPError, ValueError) as exc:
            observations.append({"service": service, "path": "/api/payments -> /api/payments/{id}", "passed": False, "error": str(exc), "observed_at": utc_iso()})
    return observations


async def collect_telemetry(settings: Settings, services: list[str]) -> dict[str, Any]:
    matcher = "|".join(services)
    queries = {
        "last_scrape_timestamp": f'max(timestamp(http_requests_total{{service=~"{matcher}"}}))',
        "error_fraction": f'(sum(rate(http_requests_total{{service=~"{matcher}",status=~"5.."}}[10s])) or vector(0)) / clamp_min(sum(rate(http_requests_total{{service=~"{matcher}"}}[10s])), 0.0001)',
        "p95_seconds": f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{service=~"{matcher}"}}[10s])) by (le))',
    }
    observed_at = datetime.now(timezone.utc)
    observations: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=8) as client:
        for name, query in queries.items():
            try:
                response = await client.get(f"{settings.prometheus_url}/api/v1/query", params={"query": query})
                response.raise_for_status()
                result = response.json().get("data", {}).get("result", [])
                values = [float(item["value"][1]) for item in result if len(item.get("value", [])) == 2 and math.isfinite(float(item["value"][1]))]
                observations[name] = values[0] if values else None
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                observations[name] = None
                observations[f"{name}_error"] = str(exc)
    scrape_timestamp = observations.get("last_scrape_timestamp")
    freshness = observed_at.timestamp() - scrape_timestamp if scrape_timestamp is not None else None
    observations.update({"freshness_seconds": freshness, "observed_at": observed_at.isoformat().replace("+00:00", "Z")})
    observations["acceptable"] = bool(freshness is not None and freshness <= 15 and observations.get("error_fraction") is not None and observations["error_fraction"] <= 0.05 and observations.get("p95_seconds") is not None and observations["p95_seconds"] < 2)
    return observations


async def verify_recovery(settings: Settings, lab: LabClient, action: dict[str, Any], services: list[str], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    rounds: list[dict[str, Any]] = []
    consecutive = 0
    async with httpx.AsyncClient() as client:
        while time.monotonic() - started <= settings.verification_timeout_seconds:
            observations = []
            for service in services:
                observations.extend(await _probe(client, service, settings))
            round_passed = bool(observations) and all(item["passed"] for item in observations)
            consecutive = consecutive + 1 if round_passed else 0
            rounds.append({"round": len(rounds) + 1, "observations": observations, "passed": round_passed})
            if consecutive >= settings.verification_rounds:
                break
            if time.monotonic() - started + settings.verification_interval_seconds > settings.verification_timeout_seconds:
                break
            await asyncio.sleep(settings.verification_interval_seconds)

    postcondition: dict[str, Any]
    if action["action_type"] == "start_service":
        postcondition = await lab.inspect_resource(action["resource_id"])
        postcondition_passed = postcondition.get("running") is True and postcondition.get("container_id") == action.get("expected_container_id")
    elif action["action_type"] == "rollback_release":
        postcondition = await lab.inspect_resource(action["resource_id"])
        postcondition_passed = postcondition.get("running") is True and postcondition.get("image_id") == action.get("previous_image_id")
    else:
        blocking = await lab.inspect_database_blocking()
        observations = blocking.get("observations", [])
        postcondition = {"database": action.get("database"), "pid": action.get("pid"), "remaining_blockers": observations}
        postcondition_passed = not any(item.get("pid") == action.get("pid") and item.get("backend_start") == action.get("backend_start") for item in observations)
    telemetry = await collect_telemetry(settings, services)
    passed = consecutive >= settings.verification_rounds and postcondition_passed and telemetry["acceptable"]
    improvement = None
    if baseline and baseline.get("error_fraction") is not None and telemetry.get("error_fraction") is not None:
        improvement = {"error_fraction_before": baseline["error_fraction"], "error_fraction_after": telemetry["error_fraction"], "change": telemetry["error_fraction"] - baseline["error_fraction"]}
    return {"status": "verified" if passed else "unverified", "passed": passed, "rounds": rounds, "postcondition": postcondition, "telemetry": telemetry, "baseline": baseline, "measured_improvement": improvement, "completed_at": utc_iso()}
