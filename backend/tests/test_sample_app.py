import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest


@pytest.fixture
def sample(monkeypatch):
    app_dir = Path(__file__).parents[2] / "sample-apps"
    sys.path.insert(0, str(app_dir))
    spec = importlib.util.spec_from_file_location("sample_app_test", app_dir / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SERVICE_KIND", "api")
    monkeypatch.setattr(module, "ship_log", AsyncMock())
    module.app.state.redis = SimpleNamespace(ping=AsyncMock(return_value=True))
    module.app.state.postgres = None
    return module


async def test_missing_database_returns_error_instead_of_fake_users(sample):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=sample.app), base_url="http://test") as client:
        response = await client.get("/api/users")
    assert response.status_code == 503
    assert "users" not in response.json()
    assert sample.POSTGRES_QUERIES.labels(sample.SERVICE_NAME, "success")._value.get() == 0


async def test_health_checks_real_dependencies(sample):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=sample.app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 503
        assert response.json()["dependencies"] == {"redis": "healthy", "postgres": "unreachable"}
        assert (await client.get("/live")).status_code == 200


async def test_lab_workload_sends_requests_without_manufacturing_metrics(sample, monkeypatch):
    requests = []
    real_client = httpx.AsyncClient
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={})
    monkeypatch.setattr(sample.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(sample.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))
    before = sample.metrics
    with pytest.raises(asyncio.CancelledError):
        await sample.lab_traffic()
    assert {request.url.path for request in requests} == {"/api/users", "/api/products"}
    assert all(request.headers["X-Traffic-Source"] == "lab-workload" for request in requests)
    assert b"http_requests_total{" not in (await before()).body


async def test_users_executes_real_postgres_query_with_timeout(sample):
    connection = SimpleNamespace(fetch=AsyncMock(return_value=[]))
    class Lease:
        async def __aenter__(self):
            return connection
        async def __aexit__(self, *args):
            pass
    sample.app.state.postgres = SimpleNamespace(acquire=lambda **kwargs: Lease())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=sample.app), base_url="http://test") as client:
        response = await client.get("/api/users")
    assert response.status_code == 200
    connection.fetch.assert_awaited_once_with("SELECT id, name, email FROM users ORDER BY id LIMIT 20", timeout=6)


async def test_sample_service_has_no_fault_control_routes(sample):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=sample.app), base_url="http://test") as client:
        assert (await client.post("/api/simulate/redis-failure", json={"enabled": True})).status_code == 404
        assert (await client.post("/api/simulate/slow-db", json={"enabled": True})).status_code == 404
        assert (await client.post("/api/simulate/bad-deployment", json={"version": "v2"})).status_code == 404
