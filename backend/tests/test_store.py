import asyncio
from datetime import timedelta

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


async def test_in_memory_store_persists_questions_in_order():
    store = InMemoryStore()
    await store.create_question({"question_id": "one", "investigation_id": "inv", "created_at": utc_now(), "question": "First"})
    await store.create_question({"question_id": "two", "investigation_id": "inv", "created_at": utc_now(), "question": "Second"})

    questions = await store.list_questions("inv")

    assert [item["question"] for item in questions] == ["First", "Second"]


async def test_expired_approval_cannot_be_approved_and_expiry_has_one_winner():
    store = InMemoryStore()
    await store.create_approval({"approval_id": "expired", "status": "pending", "expires_at": utc_now() - timedelta(seconds=1)})
    assert not await store.decide_approval("expired", "approved")
    results = await asyncio.gather(store.decide_approval("expired", "expired"), store.decide_approval("expired", "expired"))
    assert results.count(True) == 1
    assert (await store.get_approval("expired"))["status"] == "expired"


async def test_approval_and_expiry_race_never_overwrites_a_human_decision():
    store = InMemoryStore()
    await store.create_approval({"approval_id": "current", "status": "pending", "expires_at": utc_now() + timedelta(minutes=1)})
    results = await asyncio.gather(store.decide_approval("current", "approved"), store.decide_approval("current", "expired"))
    assert results == [True, False]
    assert (await store.get_approval("current"))["status"] == "approved"


async def test_investigation_resolution_can_be_claimed_only_once():
    store = InMemoryStore()
    await store.create_investigation({"incident_id": "waiting", "status": "awaiting_approval"})
    results = await asyncio.gather(*[
        store.transition_investigation("waiting", "awaiting_approval", {"status": "reporting"}) for _ in range(2)
    ])
    assert results.count(True) == 1
