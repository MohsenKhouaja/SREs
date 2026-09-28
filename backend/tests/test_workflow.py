import json
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.app.config import Settings
from backend.app.events import EventHub
from backend.app.llm import LLMUnavailable
from backend.app.store import InMemoryStore
from backend.app.workflow import InvestigationWorkflow


def test_database_action_uses_configured_production_database():
    workflow = InvestigationWorkflow(InMemoryStore(), EventHub(), Settings(sample_database_name="sres_production"))
    action = {
        "action_type": "terminate_blocking_session", "resource_id": "postgres:sres_production",
        "database": "sres_production", "pid": 42, "backend_start": "2026-09-28T00:00:00Z",
    }
    assert workflow._validate_action(action, {"observed": action})["database"] == "sres_production"
    assert "database=sres_production" in workflow.lab_actions["terminate_blocking_session"]["required_identity"]
    unrelated = {**action, "database": "incident_db", "resource_id": "postgres:incident_db"}
    with pytest.raises(ValueError, match="observed database"):
        workflow._validate_action(unrelated, {"observed": unrelated})


class ModelDouble:
    """Test-only model responses; no runtime code imports these fixtures."""
    enabled = True

    def __init__(self, insufficient=False):
        self.calls = []
        self.insufficient = insufficient

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        name = kwargs["agent_name"]
        if name in {"log", "metrics", "event"}:
            output = {"finding": "Observed database request delay", "insufficient_evidence": False}
        elif name == "correlation":
            evidence = json.loads(kwargs["user_prompt"])["evidence"]
            finding_id = evidence["events"][0]["finding_id"]
            output = {"root_cause": "Redis is stopped", "summary": "Dependent requests fail while Redis is stopped", "affected_services": ["api-server", "payment-service"], "hypotheses": [{"explanation": "Redis is stopped", "supporting_finding_ids": [finding_id], "limitations": "Controlled lab"}], "insufficient_evidence": self.insufficient, "assessment": "insufficient_evidence" if self.insufficient else "incident_detected", "recommendation": "Start the observed Redis container", "proposed_action": None if self.insufficient else {"action_type": "start_service", "resource_id": "redis", "expected_container_id": "redis-container", "supporting_finding_ids": [finding_id], "supporting_observation_ids": ["obs-inspect_runtime_resource-redis"]}}
        else:
            output = {"summary": "Investigation report", "root_cause": "Database delay", "recommendation": "Review evidence", "affected_services": ["api-server"]}
        return output, {"run_id": f"run-{name}", "agent": name, "provider": "groq", "model": "test", "status": "completed", "tool_calls": []}


async def collect_observation(_incident_id, _agent_name, evidence_tool, arguments):
    if evidence_tool.name == "query_loki":
        data = [{"stream": {"service": "api-server"}, "values": [["1787220020000000000", "Actual recorded request"]]}]
    elif evidence_tool.name == "query_prometheus":
        data = [{"metric": {"service": "api-server", "status": "503"}, "values": [[1787220020, "2"]]}]
    elif evidence_tool.name == "inspect_runtime_resource":
        resource_id = arguments["resource_id"]
        data = {"resource_id": resource_id, "container_id": f"{resource_id}-container", "running": resource_id != "redis"}
    elif evidence_tool.name == "inspect_database_blocking":
        data = {"observations": []}
    else:
        data = {"current": {"resource_id": "sample-api", "container_id": "sample-api-container"}, "history": []}
    return {
        "name": evidence_tool.name,
        "arguments": arguments,
        "result": {"status": "success", "data": data, "metadata": {"observation_id": f"obs-{evidence_tool.name}-{arguments.get('resource_id', 'global')}"}},
        "status": "completed",
    }


async def make_workflow(insufficient=False):
    store = InMemoryStore()
    workflow = InvestigationWorkflow(store, EventHub(), Settings(environment="test", use_in_memory_store=True, investigation_warmup_seconds=0, groq_api_key=""))
    workflow.llm = ModelDouble(insufficient)
    workflow._collect_tool = AsyncMock(side_effect=collect_observation)
    await workflow.create("test", {"services": ["api-server", "payment-service"], "symptom": "Dependent requests fail"})
    workflow.start("test")
    await workflow.tasks["test"]
    return workflow, store


async def test_workflow_pauses_and_closes_on_rejection_with_real_event_timestamps():
    workflow, store = await make_workflow()
    assert (await store.get_investigation("test"))["status"] == "awaiting_approval"
    approval = (await store.list_approvals("test"))[0]
    assert approval["action_type"] == "start_service"
    assert approval["parameters"] == {"resource_id": "redis", "expected_container_id": "redis-container"}
    assert approval["supporting_observation_ids"] == ["obs-inspect_runtime_resource-redis"]
    assert "synthesis" not in approval["evidence"]
    await workflow.resume("test", False)
    completed = await store.get_investigation("test")
    assert completed["status"] == "completed_with_rejection"
    assert (await store.get_approval(approval["approval_id"]))["status"] == "rejected"
    assert completed["report_json"]["timeline"] == [{"time": "2026-08-20T10:00:20+00:00", "event": "Actual recorded request", "source": "api-server"}]
    assert {call["agent_name"] for call in workflow.llm.calls} == {"log", "metrics", "event", "correlation", "report"}
    for call in workflow.llm.calls:
        assert "redis-unavailable" not in call["user_prompt"]
        assert "fallback" not in call


def test_observed_events_use_application_timestamp_and_message():
    raw = json.dumps({"timestamp": "2026-08-20T10:00:19+00:00", "service": "api-server", "message": "GET /api/users 503 2ms"})
    audit = {
        "tool_calls": [
            {
                "name": "query_loki",
                "result": {
                    "status": "success",
                    "data": [{"stream": {"service": "api-server"}, "values": [["1787220020000000000", raw]]}],
                },
            }
        ]
    }

    assert InvestigationWorkflow._observed_events(audit) == [
        {"time": "2026-08-20T10:00:19+00:00", "event": "GET /api/users 503 2ms", "source": "api-server"}
    ]


def test_action_citation_must_contain_its_frozen_resource_identity():
    action = {
        "action_type": "start_service",
        "resource_id": "redis",
        "expected_container_id": "redis-container",
        "supporting_observation_ids": ["sample-api-observation"],
    }
    evidence = {
        "events": [
            {
                "infrastructure_observations": [
                    {
                        "result": {
                            "data": {"resource_id": "sample-api", "container_id": "sample-api-container"},
                            "metadata": {"observation_id": "sample-api-observation"},
                        }
                    }
                ]
            }
        ]
    }
    with pytest.raises(ValueError, match="not supported"):
        InvestigationWorkflow._validate_action_observations(action, evidence)


async def test_no_model_means_failed_run_no_findings_and_no_approval():
    store = InMemoryStore()
    workflow = InvestigationWorkflow(store, EventHub(), Settings(investigation_warmup_seconds=0, groq_api_key=""))
    workflow._collect_tool = AsyncMock(side_effect=collect_observation)
    await workflow.create("no-model", {"services": ["api-server"], "symptom": "Requests fail"})
    workflow.start("no-model")
    await workflow.tasks["no-model"]
    assert (await store.get_investigation("no-model"))["status"] == "failed"
    assert await store.list_approvals("no-model") == []
    states = await store.list_agent_states("no-model")
    assert not any(agent["findings"] for agent in states)
    assert any(run["status"] == "failed" for agent in states for run in agent.get("llm_runs", []))


async def test_insufficient_evidence_does_not_create_approval_or_execute():
    workflow, store = await make_workflow(insufficient=True)
    assert (await store.get_investigation("test"))["status"] == "inconclusive"
    assert await store.list_approvals("test") == []


async def test_cancel_marks_investigation_terminal():
    store = InMemoryStore()
    workflow = InvestigationWorkflow(store, EventHub(), Settings(investigation_warmup_seconds=30, groq_api_key=""))
    await workflow.create("cancel", {"services": ["api-server"], "symptom": "Requests fail"})
    workflow.start("cancel")
    await workflow.cancel("cancel")
    assert (await store.get_investigation("cancel"))["status"] == "cancelled"


async def test_question_rejects_invented_citations_and_persists_valid_answer():
    workflow, store = await make_workflow()
    agents = await store.list_agent_states("test")
    citation = agents[0]["findings"][0]["finding_id"]
    response = {"answer": "Recorded observation", "citations": [citation, "invented"], "insufficient_evidence": False}
    workflow.llm.run = AsyncMock(return_value=(response, {"status": "completed"}))
    with pytest.raises(LLMUnavailable, match="valid investigation evidence"):
        await workflow.answer_question("test", "What happened?")
    assert await store.list_questions("test") == []
    response["citations"] = [citation]
    answer = await workflow.answer_question("test", "What happened?")
    assert answer["citations"] == [citation]
    assert len(await store.list_questions("test")) == 1


@pytest.mark.parametrize("verified,expected", [(True, "completed"), (False, "remediation_failed")])
async def test_execution_uses_frozen_approved_action_and_requires_recovery_checks(monkeypatch, verified, expected):
    workflow, store = await make_workflow()
    workflow.lab.execute = AsyncMock(return_value={"status": "succeeded", "result": {}})
    monkeypatch.setattr("backend.app.workflow.collect_telemetry", AsyncMock(return_value={"error_fraction": 1.0}))
    monkeypatch.setattr("backend.app.workflow.verify_recovery", AsyncMock(return_value={"status": "verified" if verified else "unverified", "passed": verified, "rounds": [], "postcondition": {}}))
    await workflow.resume("test", True)
    document = await store.get_investigation("test")
    assert document["status"] == expected
    workflow.lab.execute.assert_awaited_once_with(
        (await store.list_approvals("test"))[0]["approval_id"],
        "test",
        "start_service",
        {"resource_id": "redis", "expected_container_id": "redis-container"},
    )
    assert "verification" in document["report_json"]["evidence"]["execution"]
