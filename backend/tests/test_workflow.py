from backend.app.config import Settings
from backend.app.events import EventHub
from backend.app.store import InMemoryStore
from backend.app.workflow import InvestigationWorkflow


async def test_workflow_fans_out_pauses_for_approval_and_closes_on_rejection():
    store = InMemoryStore()
    workflow = InvestigationWorkflow(
        store,
        EventHub(),
        Settings(environment="test", use_in_memory_store=True, simulation_warmup_seconds=0),
    )
    investigation_id = "workflow-test"
    await workflow.create(investigation_id, "bad-deployment")
    workflow.start(investigation_id, "bad-deployment")
    await workflow.tasks[investigation_id]

    paused = await store.get_investigation(investigation_id)
    assert paused and paused["status"] == "awaiting_approval"
    agents = {item["agent_name"]: item for item in await store.list_agent_states(investigation_id)}
    assert all(agents[name]["status"] == "completed" for name in ("log", "metrics", "event", "correlation"))
    assert agents["report"]["status"] == "waiting"
    approvals = await store.list_approvals(investigation_id)
    assert len(approvals) == 1 and approvals[0]["status"] == "pending"
    assert {"logs", "metrics", "events", "hypotheses"} <= approvals[0]["evidence"].keys()

    await workflow.resume(investigation_id, False)
    completed = await store.get_investigation(investigation_id)
    assert completed and completed["status"] == "completed_with_rejection"
    assert completed["report_json"]["root_cause"]
    approval = await store.get_approval(approvals[0]["approval_id"])
    assert approval and approval["status"] == "rejected"


async def test_cancel_marks_investigation_terminal():
    store = InMemoryStore()
    workflow = InvestigationWorkflow(store, EventHub(), Settings(environment="test", simulation_warmup_seconds=30))
    await workflow.create("cancel-me", "slow-db")
    workflow.start("cancel-me", "slow-db")
    await workflow.cancel("cancel-me")
    document = await store.get_investigation("cancel-me")
    assert document and document["status"] == "cancelled"
