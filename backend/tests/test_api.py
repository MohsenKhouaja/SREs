from unittest.mock import AsyncMock

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models import utc_now
from backend.app.store import InMemoryStore


async def test_api_create_list_detail_cancel_and_errors(monkeypatch):
    app = create_app(
        Settings(environment="test", use_in_memory_store=True, investigation_warmup_seconds=30, groq_api_key="test"),
        InMemoryStore(),
    )
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/investigations", json={"services": ["api-server"], "symptom": "Requests are slow", "auto_start_investigation": False})
            assert created.status_code == 202
            investigation_id = created.json()["investigation_id"]
            detail = await client.get(f"/investigation/{investigation_id}")
            assert detail.status_code == 200
            assert set(detail.json()["agents"]) == {"log", "metrics", "event", "correlation", "report"}
            listed = await client.get("/investigations")
            assert listed.json()["investigations"][0]["investigation_id"] == investigation_id
            assert "report_json" not in listed.json()["investigations"][0]
            cancelled = await client.post(f"/investigation/{investigation_id}/cancel")
            assert cancelled.json()["status"] == "cancelled"
            missing = await client.get("/investigation/unknown")
            assert missing.status_code == 404


async def test_runtime_settings_api_is_removed():
    app = create_app(Settings(environment="test", use_in_memory_store=True), InMemoryStore())
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/settings")).status_code == 404
            assert (await client.post("/settings", json={})).status_code == 404


async def test_question_requires_existing_evidence(monkeypatch):
    app = create_app(Settings(environment="test", use_in_memory_store=True, groq_api_key="test"), InMemoryStore())
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/investigations", json={"services": ["api-server"], "symptom": "Requests are slow", "auto_start_investigation": False})
            investigation_id = created.json()["investigation_id"]
            response = await client.post(
                f"/investigation/{investigation_id}/questions",
                json={"question": "What happened?"},
            )
            assert response.status_code == 409


async def test_frontend_origins_are_allowed_on_port_3001():
    app = create_app(Settings(environment="test", use_in_memory_store=True), InMemoryStore())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for origin in ("http://localhost:3001", "http://127.0.0.1:3001"):
            response = await client.options(
                "/investigations",
                headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
            )

            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == origin


async def test_sse_closes_cleanly_when_subscription_ends():
    store = InMemoryStore()
    app = create_app(Settings(environment="test", use_in_memory_store=True), store)
    async with LifespanManager(app):
        await app.state.workflow.create("stream-test", {"services": ["api-server"], "symptom": "Requests fail"})

        async def finite_subscription(_investigation_id):
            yield {"type": "test", "status": "completed"}

        app.state.events.subscribe = finite_subscription
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            async with client.stream("GET", "/stream/investigation/stream-test") as response:
                lines = [line async for line in response.aiter_lines() if line]

        assert response.status_code == 200
        assert lines == ['data: {"type": "test", "status": "completed"}']


async def test_missing_model_configuration_prevents_fault_injection(monkeypatch):
    create_run = AsyncMock()
    monkeypatch.setattr("backend.app.lab_client.LabClient.create_run", create_run)
    app = create_app(Settings(use_in_memory_store=True, groq_api_key=""), InMemoryStore())
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/lab/runs", json={"scenario": "database-blocking"})
    assert response.status_code == 503
    create_run.assert_not_called()


async def test_lab_launcher_keeps_ground_truth_out_of_investigation_context(monkeypatch):
    monkeypatch.setattr(
        "backend.app.lab_client.LabClient.create_run",
        AsyncMock(return_value={"run_id": "run-12345678", "expires_at": "2026-09-22T12:00:00Z"}),
    )
    app = create_app(Settings(environment="test", use_in_memory_store=True, groq_api_key="test"), InMemoryStore())
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/lab/runs", json={"scenario": "redis-unavailable", "auto_start_investigation": False})
            detail = await client.get(f"/investigation/{response.json()['investigation_id']}")
    assert response.status_code == 202
    assert detail.json()["lab_run_id"] == "run-12345678"
    assert detail.json()["symptom"] == "Dependent application requests are returning errors."


async def test_historical_version_two_records_are_readable_but_pre_versioned_records_are_hidden():
    store = InMemoryStore()
    app = create_app(Settings(environment="test", use_in_memory_store=True), store)
    async with LifespanManager(app):
        await store.create_investigation(
            {
                "incident_id": "legacy",
                "scenario": "slow-db",
                "status": "completed",
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "completed_at": utc_now(),
                "report_json": {"root_cause": "scripted"},
                "report_markdown": "scripted",
            }
        )
        await store.create_investigation(
            {
                "incident_id": "historical",
                "scenario": "slow-db",
                "status": "completed",
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "completed_at": utc_now(),
                "report_json": {},
                "report_markdown": "",
                "evidence_version": 2,
            }
        )
        await store.create_approval(
            {
                "approval_id": "legacy-approval",
                "investigation_id": "legacy",
                "status": "approved",
                "created_at": utc_now(),
            }
        )
        await app.state.workflow.create("current", {"services": ["api-server"], "symptom": "Requests fail"})

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            listed = await client.get("/investigations")
            approvals = await client.get("/approvals")
            legacy = await client.get("/investigation/legacy")
            legacy_approval = await client.get("/approvals/legacy-approval")

    assert [item["investigation_id"] for item in listed.json()["investigations"]] == ["current", "historical"]
    assert approvals.json() == {"approvals": []}
    assert legacy.status_code == 404
    assert legacy_approval.status_code == 404
