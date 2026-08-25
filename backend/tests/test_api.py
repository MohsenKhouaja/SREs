from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.store import InMemoryStore


async def test_api_create_list_detail_cancel_and_errors():
    app = create_app(
        Settings(environment="test", use_in_memory_store=True, simulation_warmup_seconds=30),
        InMemoryStore(),
    )
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/simulate/slow-db", json={"auto_start_investigation": False})
            assert created.status_code == 202
            investigation_id = created.json()["investigation_id"]
            detail = await client.get(f"/investigation/{investigation_id}")
            assert detail.status_code == 200
            assert set(detail.json()["agents"]) == {"log", "metrics", "event", "correlation", "report"}
            listed = await client.get("/investigations")
            assert listed.json()["investigations"][0]["investigation_id"] == investigation_id
            cancelled = await client.post(f"/investigation/{investigation_id}/cancel")
            assert cancelled.json()["status"] == "cancelled"
            missing = await client.get("/investigation/unknown")
            assert missing.status_code == 404


async def test_runtime_settings_never_echo_secrets():
    app = create_app(Settings(environment="test", use_in_memory_store=True), InMemoryStore())
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/settings", json={"llm_provider": "openai", "api_key": "secret-value"})
            assert response.status_code == 200
            assert "secret-value" not in response.text
            current = await client.get("/settings")
            assert current.json() == {"llm_provider": "openai", "api_key_configured": True, "environment": "test"}

            groq = await client.post("/settings", json={"llm_provider": "groq", "api_key": "gsk-secret-value"})
            assert groq.status_code == 200
            assert "gsk-secret-value" not in groq.text
            assert groq.json()["api_key_configured"] is True
            current = await client.get("/settings")
            assert current.json() == {"llm_provider": "groq", "api_key_configured": True, "environment": "test"}
