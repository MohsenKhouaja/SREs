from types import SimpleNamespace

import httpx

from backend.app.config import Settings
from backend.app.verification import verify_recovery


class LabDouble:
    async def inspect_resource(self, resource_id):
        return {"resource_id": resource_id, "container_id": "redis-id", "running": True, "image_id": "sha256:v1"}

    async def inspect_database_blocking(self):
        return {"observations": []}


async def test_recovery_requires_exact_payment_readback_and_fresh_telemetry(monkeypatch):
    real_client = httpx.AsyncClient

    def handler(request):
        if request.url.host == "prometheus":
            query = request.url.params["query"]
            value = "0" if "status=~" in query else "0.1"
            if "timestamp(" in query:
                import time
                value = str(time.time())
            return httpx.Response(200, json={"data": {"result": [{"value": [0, value]}]}})
        if request.method == "POST":
            return httpx.Response(200, json={"payment_id": "payment-1", "status": "processed"})
        if request.url.path.endswith("payment-1"):
            return httpx.Response(200, json={"payment_id": "payment-1", "status": "processed"})
        return httpx.Response(200, json={})

    monkeypatch.setattr("backend.app.verification.httpx.AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    settings = Settings(
        sample_payment_url="http://payment",
        prometheus_url="http://prometheus",
        verification_rounds=3,
        verification_interval_seconds=0,
        verification_timeout_seconds=2,
    )
    result = await verify_recovery(settings, LabDouble(), {"action_type": "start_service", "resource_id": "redis", "expected_container_id": "redis-id"}, ["payment-service"])
    assert result["passed"] is True
    assert len(result["rounds"]) == 3


async def test_unknown_payment_never_counts_as_recovery(monkeypatch):
    real_client = httpx.AsyncClient

    def handler(request):
        if request.url.host == "prometheus":
            return httpx.Response(200, json={"data": {"result": []}})
        if request.method == "POST":
            return httpx.Response(200, json={"payment_id": "payment-1", "status": "processed"})
        return httpx.Response(200, json={"payment_id": "payment-1", "status": "unknown"})

    monkeypatch.setattr("backend.app.verification.httpx.AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    settings = Settings(sample_payment_url="http://payment", prometheus_url="http://prometheus", verification_rounds=1, verification_interval_seconds=0, verification_timeout_seconds=0.1)
    result = await verify_recovery(settings, LabDouble(), {"action_type": "start_service", "resource_id": "redis", "expected_container_id": "redis-id"}, ["payment-service"])
    assert result["passed"] is False
    assert result["rounds"][0]["observations"][0]["passed"] is False
