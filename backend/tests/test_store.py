from backend.app.models import utc_now
from backend.app.store import InMemoryStore


async def test_in_memory_store_keeps_agents_isolated_and_lists_newest_first():
    store = InMemoryStore()
    older = utc_now()
    await store.create_investigation({"incident_id": "one", "scenario": "slow-db", "status": "investigating", "created_at": older})
    await store.create_investigation({"incident_id": "two", "scenario": "redis-failure", "status": "completed", "created_at": utc_now()})
    await store.upsert_agent_state("one", "log", {"status": "completed", "findings": [{"message": "log"}]})
    await store.upsert_agent_state("one", "metrics", {"status": "running", "findings": []})
    assert [item["incident_id"] for item in await store.list_investigations()] == ["two", "one"]
    agents = await store.list_agent_states("one")
    assert {agent["agent_name"] for agent in agents} == {"log", "metrics"}
    assert next(agent for agent in agents if agent["agent_name"] == "log")["findings"][0]["message"] == "log"
