from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import var_child_runnable_config
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, interrupt

from .config import Settings
from .events import EventHub
from .lab_client import LabClient, LabControllerUnavailable
from .llm import GroqAgentRuntime, LLMUnavailable
from .models import (
    AgentFindingOutput,
    CorrelationOutput,
    Finding,
    IncidentState,
    QuestionOutput,
    ReportJSON,
    ReportOutput,
    utc_iso,
    utc_now,
)
from .store import Store, approval_expired
from .tools import (
    format_report,
    query_loki,
    query_prometheus,
    inspect_database_blocking,
    inspect_release_history,
    inspect_runtime_resource,
)
from .verification import collect_telemetry, verify_recovery


SCENARIOS = {"redis-unavailable", "database-blocking", "release-regression"}
logger = logging.getLogger(__name__)

# This catalog describes permitted lab operations, never the diagnosis or selected action.
LAB_ACTIONS = {
    "start_service": {
        "description": "Start the observed stopped Redis service.",
        "required_identity": ["resource_id=redis", "expected_container_id"],
    },
    "terminate_blocking_session": {
        "description": "Terminate the observed PostgreSQL session currently holding the application-blocking lock.",
        "required_identity": ["resource_id=postgres:incident_db", "database=incident_db", "pid", "backend_start"],
    },
    "rollback_release": {
        "description": "Replace the current sample API image with the prepared v1 image from the newest release transition whose destination container matches the current observation.",
        "required_identity": ["resource_id=sample-api", "expected_container_id", "expected_current_image_id", "previous_image_id"],
    },
}


def _compact_findings(findings: list[Finding]) -> list[dict[str, Any]]:
    """Keep downstream LLM context grounded without replaying raw tool payloads."""
    compacted = []
    for finding in findings:
        item = {key: finding.get(key) for key in ("finding_id", "timestamp", "source", "message")}
        infrastructure = [
            _compact_infrastructure_observation(observation)
            for observation in finding.get("raw_data", {}).get("observations", [])
            if observation.get("name")
            in {"inspect_runtime_resource", "inspect_database_blocking", "inspect_release_history"}
        ]
        if infrastructure:
            item["infrastructure_observations"] = infrastructure
        compacted.append(item)
    return compacted


def _pick(value: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: value[key] for key in keys if key in value}


def _container_identity(value: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        value,
        (
            "observation_id",
            "resource_id",
            "container_id",
            "state",
            "running",
            "health",
            "image_id",
            "image_tags",
            "started_at",
            "observed_at",
        ),
    )


def _compact_infrastructure_observation(observation: dict[str, Any]) -> dict[str, Any]:
    result = observation.get("result", {})
    data = result.get("data", {})
    name = observation.get("name")
    compact_data: Any = data
    if name == "inspect_runtime_resource" and isinstance(data, dict):
        compact_data = _container_identity(data)
    elif name == "inspect_database_blocking" and isinstance(data, dict):
        compact_data = {
            "observations": [
                _pick(
                    row,
                    (
                        "observation_id",
                        "resource_id",
                        "database",
                        "pid",
                        "backend_start",
                        "application_name",
                        "blocked_pid",
                        "blocked_application",
                        "wait_event_type",
                        "wait_event",
                        "blocker_query",
                        "blocked_query",
                        "observed_at",
                    ),
                )
                for row in data.get("observations", [])
            ]
        }
    elif name == "inspect_release_history" and isinstance(data, dict):
        compact_data = {
            "current": _container_identity(data.get("current", {})),
            "history": [
                {
                    **_pick(entry, ("run_id", "action_id", "observed_at")),
                    "from": _container_identity(entry.get("from", {})),
                    "to": _container_identity(entry.get("to", {})),
                }
                for entry in data.get("history", [])[:3]
            ],
        }
    return {
        "name": name,
        "arguments": observation.get("arguments", {}),
        "status": observation.get("status"),
        "result": {
            "status": result.get("status"),
            "data": compact_data,
            "metadata": _pick(result.get("metadata", {}), ("observation_id", "observed_at", "source", "error")),
        },
    }


def _observation_ids(value: Any) -> set[str]:
    """Collect immutable observation references from nested tool results."""
    if isinstance(value, dict):
        identifiers = {value["observation_id"]} if isinstance(value.get("observation_id"), str) else set()
        for nested in value.values():
            identifiers.update(_observation_ids(nested))
        return identifiers
    if isinstance(value, list):
        identifiers: set[str] = set()
        for nested in value:
            identifiers.update(_observation_ids(nested))
        return identifiers
    return set()


def _index_observation_ids(value: Any, index: dict[str, Any] | None = None) -> dict[str, Any]:
    """Map each observation ID to the evidence object that identity represents."""
    indexed = index if index is not None else {}
    if isinstance(value, dict):
        identifier = value.get("observation_id")
        if isinstance(identifier, str):
            indexed.setdefault(identifier, value)
        result = value.get("result")
        if isinstance(result, dict):
            metadata = result.get("metadata", {})
            metadata_id = metadata.get("observation_id") if isinstance(metadata, dict) else None
            if isinstance(metadata_id, str):
                indexed[metadata_id] = result.get("data", {})
        for nested in value.values():
            _index_observation_ids(nested, indexed)
    elif isinstance(value, list):
        for nested in value:
            _index_observation_ids(nested, indexed)
    return indexed


class InvestigationWorkflow:
    def __init__(self, store: Store, events: EventHub, settings: Settings, checkpointer: Any | None = None) -> None:
        self.store = store
        self.events = events
        self.settings = settings
        self.lab_actions = {
            **LAB_ACTIONS,
            "terminate_blocking_session": {
                **LAB_ACTIONS["terminate_blocking_session"],
                "required_identity": [
                    f"resource_id=postgres:{settings.sample_database_name}",
                    f"database={settings.sample_database_name}", "pid", "backend_start",
                ],
            },
        }
        self.llm = GroqAgentRuntime(settings)
        self.llm_semaphore = asyncio.Semaphore(1)
        self.lab = LabClient(settings)
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.graph = self._build_graph(checkpointer or InMemorySaver())

    def _build_graph(self, checkpointer: Any):
        builder = StateGraph(IncidentState)
        api_retry = RetryPolicy(max_attempts=3, initial_interval=0.5)
        builder.add_node("log", self._log_agent, retry_policy=api_retry)
        builder.add_node("metrics", self._metrics_agent, retry_policy=api_retry)
        builder.add_node("event", self._event_agent, retry_policy=api_retry)
        builder.add_node("correlation", self._correlation_agent)
        builder.add_node("approval", self._approval_node)
        builder.add_node("record_decision", self._record_approval_decision)
        builder.add_node("execute", self._execute_remediation)
        builder.add_node("report", self._report_agent)
        builder.add_node("rejected", self._rejected_report)
        builder.add_edge(START, "log")
        builder.add_edge(START, "metrics")
        builder.add_edge(START, "event")
        builder.add_edge(["log", "metrics", "event"], "correlation")
        builder.add_conditional_edges("correlation", lambda state: "approval" if state.get("pending_approval") else "report")
        builder.add_edge("approval", "record_decision")
        builder.add_conditional_edges("record_decision", self._route_approval, {"approved": "execute", "rejected": "rejected"})
        builder.add_edge("execute", "report")
        builder.add_edge("report", END)
        builder.add_edge("rejected", END)
        return builder.compile(checkpointer=checkpointer)

    async def create(self, investigation_id: str, context: dict[str, Any], lab_run_id: str | None = None) -> None:
        now = utc_now()
        time_to = context.get("time_to") or now
        time_from = context.get("time_from") or (time_to - timedelta(minutes=5))
        await self.store.create_investigation(
            {
                "incident_id": investigation_id,
                "scenario": context.get("scenario", "manual"),
                "services": context["services"],
                "symptom": context["symptom"],
                "observation_start": time_from,
                "observation_end": time_to,
                "lab_run_id": lab_run_id,
                "status": "investigating",
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
                "report_json": {},
                "report_markdown": "",
                "evidence_version": 3,
                "assessment": None,
                "recovery_origin": None,
            }
        )
        for name in ("log", "metrics", "event", "correlation", "report"):
            await self.store.upsert_agent_state(
                investigation_id,
                name,
                {"findings": [], "steps": [], "llm_runs": [], "status": "waiting", "started_at": None, "completed_at": None},
            )

    def start(self, investigation_id: str) -> None:
        self.tasks[investigation_id] = asyncio.create_task(self._run_initial(investigation_id))

    async def _run_initial(self, investigation_id: str) -> None:
        try:
            if self.settings.investigation_warmup_seconds:
                await asyncio.sleep(self.settings.investigation_warmup_seconds)
            document = await self.store.get_investigation(investigation_id)
            if not document:
                raise KeyError(investigation_id)
            observation_start = datetime.fromisoformat(document["observation_start"].replace("Z", "+00:00"))
            observation_end = datetime.fromisoformat(document["observation_end"].replace("Z", "+00:00"))
            if document.get("lab_run_id"):
                created_at = datetime.fromisoformat(document["created_at"].replace("Z", "+00:00"))
                observation_start = created_at - timedelta(seconds=5)
                observation_end = utc_now()
                await self.store.update_investigation(
                    investigation_id,
                    {"observation_start": observation_start, "observation_end": observation_end},
                )
            state: IncidentState = {
                "incident_id": investigation_id,
                "services": document["services"],
                "symptom": document["symptom"],
                "log_findings": [],
                "metrics_findings": [],
                "event_findings": [],
                "correlation_summary": "",
                "root_cause": "",
                "affected_services": [],
                "report_json": {},
                "report_markdown": "",
                "pending_approval": None,
                "approval_result": "",
                "agent_steps": [],
                "status": "investigating",
                "observation_start": str(observation_start.timestamp()),
                "observation_end": str(observation_end.timestamp()),
                "lab_run_id": document.get("lab_run_id"),
            }
            result = await asyncio.wait_for(
                self.graph.ainvoke(state, config=self._config(investigation_id)), timeout=300
            )
            if result.get("__interrupt__"):
                await self.store.update_investigation(investigation_id, {"status": "awaiting_approval"})
                await self.events.publish(investigation_id, {"type": "approval_required", "status": "awaiting_approval"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail(investigation_id, exc)

    async def resolve_approval(self, investigation_id: str, approval_id: str, decision: str) -> bool:
        approval = await self.store.get_approval(approval_id)
        if not approval or approval["investigation_id"] != investigation_id or approval.get("evidence_version") != 3:
            return False
        if approval["status"] == "pending":
            if not await self.store.decide_approval(approval_id, decision):
                return False
        elif approval["status"] != decision:
            return False
        if not await self.store.transition_investigation(
            investigation_id, "awaiting_approval", {"status": "investigating" if decision == "approved" else "reporting", "approval_outcome": decision},
        ):
            return False
        self.tasks[investigation_id] = asyncio.create_task(self._resume(investigation_id, decision))
        return True

    async def resume(self, investigation_id: str, approved: bool) -> None:
        approvals = await self.store.list_approvals(investigation_id)
        if not approvals or not await self.resolve_approval(investigation_id, approvals[0]["approval_id"], "approved" if approved else "rejected"):
            raise ValueError("Approval is no longer pending or executable")
        await self.tasks[investigation_id]

    async def _resume(self, investigation_id: str, decision: str) -> None:
        try:
            snapshot = await self.graph.aget_state(self._config(investigation_id))
            if not snapshot.values or not snapshot.next:
                raise ValueError("The investigation checkpoint is unavailable; collect fresh evidence")
            await asyncio.wait_for(
                self.graph.ainvoke(Command(resume=decision), config=self._config(investigation_id)), timeout=300
            )
        except Exception as exc:
            await self._fail(investigation_id, exc)

    async def reconcile(self, *, startup: bool = False) -> None:
        for document in await self.store.list_investigations():
            if document.get("evidence_version") != 3:
                continue
            investigation_id = document["incident_id"]
            task = self.tasks.get(investigation_id)
            active = bool(task and not task.done())
            try:
                lab_closed = False
                if document.get("lab_run_id") and not document.get("lab_cleanup"):
                    try:
                        run = await self.lab.get_run(document["lab_run_id"])
                    except LabControllerUnavailable:
                        run = {}
                    lab_closed = run.get("status") in {"cleaned", "expired", "remediated"}
                    if lab_closed:
                        await self.store.update_investigation(investigation_id, {"lab_cleanup": run.get("cleanup"), "recovery_origin": (run.get("cleanup") or {}).get("origin")})
                elif document.get("lab_cleanup"):
                    lab_closed = True
                if active:
                    continue
                if startup and document["status"] in {"investigating", "reporting"}:
                    agents = await self.store.list_agent_states(investigation_id)
                    if any(agent.get("started_at") for agent in agents):
                        await self._fail(investigation_id, RuntimeError("Investigation interrupted by backend restart; no operation was replayed"))
                    continue
                if document["status"] != "awaiting_approval":
                    continue
                approvals = await self.store.list_approvals(investigation_id)
                if not approvals:
                    await self._fail(investigation_id, ValueError("Waiting investigation has no approval record"))
                    continue
                approval = approvals[0]
                if approval["status"] == "pending":
                    decision = "expired" if approval_expired(approval) else "invalidated" if lab_closed else None
                    if not decision:
                        continue
                    if not await self.store.decide_approval(approval["approval_id"], decision):
                        continue
                    if decision == "invalidated":
                        await self.store.update_approval(approval["approval_id"], {"invalidation_reason": "lab_run_closed"})
                    approval["status"] = decision
                if approval["status"] in {"expired", "invalidated", "rejected"}:
                    await self.resolve_approval(investigation_id, approval["approval_id"], approval["status"])
                elif startup and approval["status"] == "approved":
                    await self._fail(investigation_id, RuntimeError("Approved investigation interrupted before execution; collect fresh evidence"))
            except Exception:
                logger.exception("Investigation reconciliation failed for %s", investigation_id)

    async def watch_expiry(self) -> None:
        while True:
            await asyncio.sleep(5)
            try:
                await self.reconcile()
            except Exception:
                logger.exception("Investigation reconciliation unavailable")

    async def cancel(self, investigation_id: str) -> None:
        task = self.tasks.get(investigation_id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.store.invalidate_pending_approvals(investigation_id, "investigation_cancelled")
        await self._close_unfinished_agents(investigation_id, "cancelled")
        await self.store.update_investigation(investigation_id, {"status": "cancelled", "completed_at": utc_now()})
        await self.events.publish(investigation_id, {"type": "investigation", "status": "cancelled"})

    @staticmethod
    def _config(investigation_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": investigation_id}, "callbacks": []}

    async def _agent_step(self, incident_id: str, agent: str, step: str) -> None:
        await self.store.upsert_agent_state(incident_id, agent, {"status": "running", "started_at": utc_now()})
        states = await self.store.list_agent_states(incident_id)
        current = next((item for item in states if item["agent_name"] == agent), {"steps": []})
        steps = [*current.get("steps", []), {"step": step}]
        await self.store.upsert_agent_state(incident_id, agent, {"steps": steps})
        await self.events.publish(incident_id, {"type": "agent_step", "agent": agent, "step": step})

    async def _complete_agent(self, incident_id: str, agent: str, findings: list[Finding]) -> None:
        await self.store.upsert_agent_state(
            incident_id, agent, {"findings": findings, "status": "completed", "completed_at": utc_now()}
        )
        await self.events.publish(incident_id, {"type": "agent_status", "agent": agent, "status": "completed", "findings": findings})

    async def _run_agent(
        self,
        incident_id: str,
        agent_name: str,
        *,
        system_prompt: str,
        user_prompt: str,
        tools: list[Any],
        response_schema: Any,
        required_evidence_tools: set[str] | None = None,
        observations: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        await self._agent_step(incident_id, agent_name, f"Preparing bounded {agent_name} analysis for Groq")
        await self.events.publish(
            incident_id,
            {"type": "llm_started", "agent": agent_name, "provider": "groq", "model": self.settings.groq_model},
        )
        failure = None
        async with self.llm_semaphore:
            try:
                output, audit = await self.llm.run(
                    agent_name=agent_name,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    tools=tools,
                    response_schema=response_schema,
                    required_evidence_tools=required_evidence_tools,
                    max_tokens=max_tokens,
                )
            except LLMUnavailable as exc:
                failure = exc
                audit = exc.audit
                if audit is None:
                    raise
        if observations:
            audit["observations"] = observations
        states = await self.store.list_agent_states(incident_id)
        current = next((item for item in states if item["agent_name"] == agent_name), {"llm_runs": []})
        await self.store.upsert_agent_state(
            incident_id,
            agent_name,
            {"llm_runs": [*current.get("llm_runs", []), audit], "execution_mode": audit["status"]},
        )
        for tool_call in audit.get("tool_calls", []):
            await self.events.publish(incident_id, {"type": "tool_call", "agent": agent_name, **tool_call})
        event_type = "llm_failed" if failure else "llm_completed"
        await self.events.publish(
            incident_id,
            {"type": event_type, "agent": agent_name, "run": audit},
        )
        if failure:
            await self.store.upsert_agent_state(incident_id, agent_name, {"status": "failed", "completed_at": utc_now()})
            raise failure
        await self._agent_step(incident_id, agent_name, "Groq response validated")
        return output, audit

    async def _collect_tool(
        self,
        incident_id: str,
        agent_name: str,
        evidence_tool: Any,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "name": evidence_tool.name,
            "arguments": arguments,
            "result": None,
            "status": "running",
        }
        await self.events.publish(
            incident_id,
            {"type": "tool_call", "agent": agent_name, **record},
        )
        try:
            result = await asyncio.to_thread(evidence_tool.invoke, arguments)
        except Exception as exc:
            result = {
                "status": "error",
                "data": [],
                "metadata": {"error": str(exc), "observed_at": utc_iso()},
            }
        record = {
            **record,
            "result": result,
            "status": "completed" if result.get("status") == "success" else "error",
        }
        await self.events.publish(
            incident_id,
            {"type": "tool_result", "agent": agent_name, **record},
        )
        return record

    @staticmethod
    def _observation_prompt(state: IncidentState) -> str:
        service_selector = "|".join(state["services"])
        return json.dumps({
            "task": "Investigate observed behavior without assuming a cause. Missing observations are not proof of health or failure.",
            "services": state["services"],
            "operator_reported_symptom": state["symptom"],
            "time_from": state["observation_start"], "time_to": state["observation_end"],
            "log_selector": f'{{service=~"{service_selector}"}}',
            "available_metrics": ["http_requests_total", "http_request_duration_seconds_bucket", "postgres_query_duration_seconds_bucket", "redis_connections_total"],
        }, separators=(",", ":"))

    @staticmethod
    def _observed_events(audit: dict[str, Any]) -> list[dict[str, Any]]:
        events = []
        for call in audit.get("tool_calls", []):
            result = call.get("result") or {}
            if call["name"] != "query_loki" or result.get("status") != "success":
                continue
            for stream in result.get("data", []):
                for timestamp, raw in stream.get("values", []):
                    recorded_at = datetime.fromtimestamp(int(timestamp) / 1e9, timezone.utc).isoformat()
                    message = raw
                    source = stream.get("stream", {}).get("service", "loki")
                    try:
                        payload = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        payload = None
                    if isinstance(payload, dict):
                        message = str(payload.get("message") or raw)
                        source = str(payload.get("service") or source)
                        if isinstance(payload.get("timestamp"), str):
                            recorded_at = payload["timestamp"]
                    events.append({"time": recorded_at, "event": message, "source": source})
        return sorted(events, key=lambda event: event["time"])

    async def _log_agent(self, state: IncidentState) -> dict[str, Any]:
        context = json.loads(self._observation_prompt(state))
        observations = [
            await self._collect_tool(
                state["incident_id"],
                "log",
                query_loki,
                {
                    "query": context["log_selector"],
                    "time_from": state["observation_start"],
                    "time_to": state["observation_end"],
                },
            )
        ]
        output, audit = await self._run_agent(
            state["incident_id"],
            "log",
            system_prompt=(
                "You are the log specialist for a controlled SRE investigation. Use at least one provided read-only "
                "log observation, stay within the supplied interval, and return one concise finding supported by it. "
                "Runtime errors are evidence; never infer health from an empty query."
            ),
            user_prompt=json.dumps({"context": context, "observations": observations}, default=str, separators=(",", ":")),
            tools=[],
            response_schema=AgentFindingOutput,
            observations=observations,
        )
        finding: Finding = {
            "finding_id": str(uuid.uuid4()),
            "timestamp": utc_iso(),
            "source": "loki",
            "message": output["finding"],
            "raw_data": {"observations": observations, "execution_mode": audit["status"], "insufficient_evidence": output["insufficient_evidence"], "events": self._observed_events({"tool_calls": observations})},
        }
        await self._complete_agent(state["incident_id"], "log", [finding])
        return {"log_findings": [finding], "agent_steps": [{"agent": "log", "step": "Result: log evidence captured"}]}

    async def _metrics_agent(self, state: IncidentState) -> dict[str, Any]:
        context = json.loads(self._observation_prompt(state))
        service_selector = "|".join(state["services"])
        observations = [
            await self._collect_tool(
                state["incident_id"],
                "metrics",
                query_prometheus,
                {
                    "query": f'sum by (service, status) (http_requests_total{{service=~"{service_selector}"}})',
                    "time_from": state["observation_start"],
                    "time_to": state["observation_end"],
                },
            )
        ]
        output, audit = await self._run_agent(
            state["incident_id"],
            "metrics",
            system_prompt=(
                "You are the metrics specialist for a controlled SRE investigation. Use at least one provided read-only "
                "metrics observation, inspect the supplied interval, and return one concise quantitative finding. "
                "State when samples are missing or stale."
            ),
            user_prompt=json.dumps({"context": context, "observations": observations}, default=str, separators=(",", ":")),
            tools=[],
            response_schema=AgentFindingOutput,
            observations=observations,
        )
        finding: Finding = {
            "finding_id": str(uuid.uuid4()),
            "timestamp": utc_iso(),
            "source": "prometheus",
            "message": output["finding"],
            "raw_data": {"observations": observations, "execution_mode": audit["status"], "insufficient_evidence": output["insufficient_evidence"]},
        }
        await self._complete_agent(state["incident_id"], "metrics", [finding])
        return {"metrics_findings": [finding], "agent_steps": [{"agent": "metrics", "step": "Result: metric evidence captured"}]}

    async def _event_agent(self, state: IncidentState) -> dict[str, Any]:
        context = json.loads(self._observation_prompt(state))
        collection_specs = [
            (query_loki, {"query": context["log_selector"], "time_from": state["observation_start"], "time_to": state["observation_end"]}),
            (inspect_runtime_resource, {"resource_id": "redis"}),
            (inspect_runtime_resource, {"resource_id": "sample-api"}),
            (inspect_database_blocking, {}),
            (inspect_release_history, {}),
        ]
        observations = await asyncio.gather(
            *(self._collect_tool(state["incident_id"], "event", evidence_tool, arguments) for evidence_tool, arguments in collection_specs)
        )
        output, audit = await self._run_agent(
            state["incident_id"],
            "event",
            system_prompt=(
                "You are the event and runtime specialist. Analyze the supplied Loki, redis, sample-api, database blocking, "
                "and release-history observations. Preserve original timestamps and identities. "
                "Never invent timestamps or infer causality from ordering alone. Use the supplied interval and state gaps explicitly."
            ),
            user_prompt=json.dumps({"context": context, "observations": observations}, default=str, separators=(",", ":")),
            tools=[],
            response_schema=AgentFindingOutput,
            observations=observations,
        )
        finding: Finding = {
            "finding_id": str(uuid.uuid4()),
            "timestamp": utc_iso(),
            "source": "loki",
            "message": output["finding"],
            "raw_data": {"events": self._observed_events({"tool_calls": observations}), "observations": observations, "execution_mode": audit["status"], "insufficient_evidence": output["insufficient_evidence"]},
        }
        await self._complete_agent(state["incident_id"], "event", [finding])
        return {"event_findings": [finding], "agent_steps": [{"agent": "event", "step": "Result: incident timeline built"}]}

    async def _correlation_agent(self, state: IncidentState) -> dict[str, Any]:
        incident_id = state["incident_id"]
        evidence = {
            "logs": _compact_findings(state["log_findings"]),
            "metrics": _compact_findings(state["metrics_findings"]),
            "events": _compact_findings(state["event_findings"]),
        }
        valid_finding_ids = {finding["finding_id"] for group in evidence.values() for finding in group}
        valid_observation_ids = _observation_ids(evidence)
        output, audit = await self._run_agent(
            incident_id,
            "correlation",
            system_prompt=(
                "You are the correlation specialist. Develop competing hypotheses from the observations. "
                "Hypothesis supporting_finding_ids and action supporting_finding_ids must contain only supplied finding IDs. "
                "Action supporting_observation_ids must contain only supplied observation IDs for the exact infrastructure identity. "
                "Explain limitations and contradictions. Never manufacture confidence scores. "
                "Select an action from the supplied operation catalog only if supported by cited findings and an observed, stable resource identity. "
                "Copy container IDs, image IDs, database PIDs, and backend start times exactly from tool observations. "
                "Otherwise return proposed_action=null. Classify the result as incident_detected, no_incident_observed, or insufficient_evidence. "
                "A healthy classification requires populated recent observations. Do not execute actions. "
                "Return at most two hypotheses. Keep every explanation and limitation to one sentence and the total response terse."
            ),
            user_prompt=json.dumps(
                {
                    "available_lab_actions": self.lab_actions,
                    "valid_finding_ids": sorted(valid_finding_ids),
                    "valid_observation_ids": sorted(valid_observation_ids),
                    "evidence": evidence,
                },
                default=str,
            ),
            tools=[],
            response_schema=CorrelationOutput,
            max_tokens=1536,
        )
        root_cause = output["root_cause"]
        summary = output["summary"]
        cited_ids = {citation for hypothesis in output["hypotheses"] for citation in hypothesis["supporting_finding_ids"]}
        if not cited_ids <= valid_finding_ids:
            raise ValueError("Correlation cited evidence that does not exist")
        action = output["proposed_action"]
        approval = None
        if output["assessment"] == "insufficient_evidence":
            output["insufficient_evidence"] = True
        if action and output["assessment"] == "incident_detected" and not output["insufficient_evidence"]:
            if not cited_ids:
                raise ValueError("Remediation requires cited observations")
            if not set(action["supporting_finding_ids"]) <= valid_finding_ids:
                raise ValueError("Proposed action cited findings that do not exist")
            if not set(action["supporting_observation_ids"]) <= valid_observation_ids:
                raise ValueError("Proposed action cited infrastructure observations that do not exist")
            self._validate_action_observations(action, evidence)
            parameters = self._validate_action(action, evidence)
            approval = {
                "approval_id": str(uuid.uuid4()),
                "action_type": action["action_type"],
                "target": action["resource_id"],
                "parameters": parameters,
                "supporting_finding_ids": action["supporting_finding_ids"],
                "supporting_observation_ids": action["supporting_observation_ids"],
                "description": LAB_ACTIONS[action["action_type"]]["description"],
                "reason": output["recommendation"],
                "evidence": {**evidence, "hypotheses": output["hypotheses"]},
                "proposed_by": "correlation",
                "proposed_at": utc_iso(),
                "evidence_version": 3,
                "expires_at": (utc_now() + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            }
            await self.store.create_approval(
                {**approval, "investigation_id": incident_id, "status": "pending", "created_at": utc_now(), "decided_at": None}
            )
        await self._complete_agent(
            incident_id,
            "correlation",
            [{"finding_id": str(uuid.uuid4()), "timestamp": utc_iso(), "source": "cross-agent", "message": root_cause, "raw_data": {"hypotheses": output["hypotheses"], "execution_mode": audit["status"], "insufficient_evidence": output["insufficient_evidence"]}}],
        )
        if approval:
            await self.events.publish(incident_id, {"type": "approval", "approval": approval, "status": "pending"})
        return {
            "correlation_summary": summary,
            "root_cause": root_cause,
            "affected_services": output["affected_services"],
            "recommendation": output["recommendation"],
            "insufficient_evidence": output["insufficient_evidence"],
            "assessment": output["assessment"],
            "pending_approval": approval,
            "status": "awaiting_approval" if approval else "investigating",
            "agent_steps": [{"agent": "correlation", "step": "Remediation proposed" if approval else "No supported remediation proposed"}],
        }

    @staticmethod
    def _validate_action_observations(action: dict[str, Any], evidence: dict[str, Any]) -> None:
        index = _index_observation_ids(evidence)
        cited = [index[identifier] for identifier in action["supporting_observation_ids"]]
        serialized = json.dumps(cited, default=str)
        required = [action["resource_id"]]
        if action["action_type"] == "start_service":
            required.append(action.get("expected_container_id"))
        elif action["action_type"] == "terminate_blocking_session":
            required.extend((action.get("database"), action.get("pid"), action.get("backend_start")))
        else:
            required.extend(
                (
                    action.get("expected_container_id"),
                    action.get("expected_current_image_id"),
                    action.get("previous_image_id"),
                )
            )
        if any(value is None or str(value) not in serialized for value in required):
            raise ValueError("Proposed action identities are not supported by its cited infrastructure observations")

    def _validate_action(self, action: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
        serialized = json.dumps(evidence, default=str)
        resource_id = action["resource_id"]
        if resource_id not in serialized:
            raise ValueError("Proposed action resource was not observed")
        if action["action_type"] == "start_service":
            container_id = action.get("expected_container_id")
            if resource_id != "redis" or not container_id or container_id not in serialized:
                raise ValueError("Starting a service requires the observed stopped Redis container identity")
            return {"resource_id": resource_id, "expected_container_id": container_id}
        if action["action_type"] == "terminate_blocking_session":
            database, pid, backend_start = action.get("database"), action.get("pid"), action.get("backend_start")
            if database != self.settings.sample_database_name or resource_id != f"postgres:{database}" or pid is None or str(pid) not in serialized or not backend_start or backend_start not in serialized:
                raise ValueError("Terminating a session requires its observed database, PID, and backend start time")
            return {"resource_id": resource_id, "database": database, "pid": pid, "backend_start": backend_start}
        expected_container_id = action.get("expected_container_id")
        current_image = action.get("expected_current_image_id")
        previous_image = action.get("previous_image_id")
        if resource_id != "sample-api" or not all((expected_container_id, current_image, previous_image)):
            raise ValueError("Rollback requires observed current container and current/previous image identities")
        if not all(value in serialized for value in (expected_container_id, current_image, previous_image)):
            raise ValueError("Rollback identities were not present in observed release evidence")
        return {"resource_id": resource_id, "expected_container_id": expected_container_id, "expected_current_image_id": current_image, "previous_image_id": previous_image}

    async def _approval_node(self, state: IncidentState, config: RunnableConfig) -> dict[str, Any]:
        """Pure interrupt gate; side effects live in the following node for resume safety."""
        token = var_child_runnable_config.set(config)
        try:
            response = interrupt(state["pending_approval"])
        finally:
            var_child_runnable_config.reset(token)
        decision = ("approved" if response else "rejected") if isinstance(response, bool) else response
        if decision not in {"approved", "rejected", "expired", "invalidated"}:
            raise ValueError("Unknown approval outcome")
        return {"approval_result": decision, "status": "investigating" if decision == "approved" else "reporting"}

    async def _record_approval_decision(self, state: IncidentState) -> dict[str, Any]:
        decision = state["approval_result"]
        approved = decision == "approved"
        approval = state["pending_approval"]
        assert approval is not None
        recorded = await self.store.get_approval(approval["approval_id"])
        if not recorded or recorded["status"] != decision:
            raise ValueError("Approval outcome changed before resuming")
        await self.store.update_investigation(state["incident_id"], {"status": "investigating" if approved else "reporting"})
        await self.events.publish(state["incident_id"], {"type": "approval", "approval_id": approval["approval_id"], "status": decision})
        return {}

    @staticmethod
    def _route_approval(state: IncidentState) -> Literal["approved", "rejected"]:
        return "approved" if state["approval_result"] == "approved" else "rejected"

    async def _execute_remediation(self, state: IncidentState) -> dict[str, Any]:
        await self.events.publish(state["incident_id"], {"type": "remediation", "status": "running"})
        try:
            approval = state["pending_approval"]
            if not approval or state.get("approval_result") != "approved" or approval.get("evidence_version") != 3:
                raise ValueError("A current, approved evidence-backed action is required")
            action_id = approval["approval_id"]
            baseline = await collect_telemetry(self.settings, state["services"])
            recorded = await self.store.get_approval(action_id)
            if not recorded or recorded["status"] != "approved" or approval_expired(recorded):
                raise ValueError("The approved operation is no longer executable; collect fresh evidence")
            if state.get("lab_run_id"):
                run = await self.lab.get_run(state["lab_run_id"])
                if run["status"] != "active" or approval_expired(run):
                    raise ValueError("The lab run closed before execution; no operation was executed")
            operation = await self.lab.execute(
                action_id,
                state["incident_id"],
                approval["action_type"],
                approval["parameters"],
            )
            if operation["status"] != "succeeded":
                result = {"status": operation["status"], "operation": operation, "recovery_origin": "agent_action", "completed_at": utc_iso()}
            else:
                action = {"action_type": approval["action_type"], **approval["parameters"]}
                verification = await verify_recovery(self.settings, self.lab, action, state["services"], baseline)
                if state.get("lab_run_id"):
                    await self.lab.complete_run(state["lab_run_id"], action_id, verification)
                result = {
                    "status": "success" if verification["passed"] else "verification_failed",
                    "operation": operation,
                    "verification": verification,
                    "recovery_origin": "agent_action",
                    "completed_at": utc_iso(),
                }
        except Exception as exc:
            result = {"status": "error", "error": str(exc), "recovery_origin": "agent_action", "completed_at": utc_iso()}
        await self.events.publish(state["incident_id"], {"type": "remediation", **result})
        return {"execution_result": result}

    async def _report_agent(self, state: IncidentState) -> dict[str, Any]:
        report, audit = await self._generate_report(state, state.get("recommendation", ""))
        assessment = state.get("assessment", "insufficient_evidence")
        status = "no_incident_observed" if assessment == "no_incident_observed" else "inconclusive" if assessment == "insufficient_evidence" or state.get("insufficient_evidence") else "completed"
        if state.get("execution_result", {}).get("status") not in (None, "success"):
            status = "remediation_failed"
        markdown = format_report.invoke({"data": report, "format": "markdown"})["data"]["report"]
        await self._complete_agent(
            state["incident_id"], "report", [{"finding_id": str(uuid.uuid4()), "timestamp": utc_iso(), "source": "report", "message": report["summary"], "raw_data": {**report, "execution_mode": audit["status"]}}]
        )
        await self.store.update_investigation(
            state["incident_id"],
            {"status": status, "assessment": assessment, "completed_at": utc_now(), "report_json": report, "report_markdown": markdown, "recovery_origin": state.get("execution_result", {}).get("recovery_origin")},
        )
        await self.events.publish(state["incident_id"], {"type": "investigation", "status": status, "report": report})
        return {"report_json": report, "report_markdown": markdown, "status": status, "pending_approval": None}

    async def _rejected_report(self, state: IncidentState) -> dict[str, Any]:
        decision = state["approval_result"]
        recommendations = {
            "rejected": "Remediation was rejected by the operator; no operational action was executed.",
            "expired": "The approval window expired without an operator decision; no agent remediation was executed. Collect fresh evidence before proposing another operation.",
            "invalidated": "The approval was invalidated because the lab run closed or the investigation stopped; no agent remediation was executed.",
        }
        status = {"rejected": "completed_with_rejection", "expired": "completed_with_expired_approval", "invalidated": "completed_with_invalidated_approval"}[decision]
        report, audit = await self._generate_report(
            state,
            recommendations[decision],
        )
        markdown = format_report.invoke({"data": report, "format": "markdown"})["data"]["report"]
        await self._complete_agent(
            state["incident_id"], "report", [{"finding_id": str(uuid.uuid4()), "timestamp": utc_iso(), "source": "report", "message": report["summary"], "raw_data": {**report, "execution_mode": audit["status"]}}]
        )
        await self.store.update_investigation(
            state["incident_id"],
            {"status": status, "assessment": state.get("assessment"), "completed_at": utc_now(), "report_json": report, "report_markdown": markdown},
        )
        await self.events.publish(state["incident_id"], {"type": "investigation", "status": status, "report": report})
        return {"report_json": report, "report_markdown": markdown, "status": status, "pending_approval": None}

    async def _generate_report(self, state: IncidentState, recommendation: str) -> tuple[ReportJSON, dict[str, Any]]:
        draft = self._build_report(state, recommendation)
        document = await self.store.get_investigation(state["incident_id"])
        if document and document.get("lab_cleanup"):
            draft["evidence"]["lab_cleanup"] = document["lab_cleanup"]
        evidence = draft["evidence"]
        output, audit = await self._run_agent(
            state["incident_id"],
            "report",
            system_prompt=(
                "You are the incident report specialist. Preserve the supplied evidence and decision outcome, "
                "write a concise report, and never claim an action succeeded unless execution evidence says so. "
                "If verification is absent, failed, or unverified, explicitly call recovery unverified and do not describe the services as healthy, recovered, or restored."
            ),
            user_prompt=json.dumps(
                {
                    "correlation": {
                        "summary": draft["summary"],
                        "root_cause": draft["root_cause"],
                        "recommendation": draft["recommendation"],
                        "affected_services": draft["affected_services"],
                    },
                    "findings": [
                        {key: finding.get(key) for key in ("finding_id", "source", "message")}
                        for finding in [*state["log_findings"], *state["metrics_findings"], *state["event_findings"]]
                    ],
                    "execution": state.get("execution_result"),
                    "approval_result": state["approval_result"],
                    "lab_cleanup": draft["evidence"].get("lab_cleanup"),
                },
                default=str,
                separators=(",", ":"),
            ),
            tools=[],
            response_schema=ReportOutput,
        )
        report: ReportJSON = {
            "summary": output["summary"],
            "root_cause": output["root_cause"],
            "evidence": evidence,
            "recommendation": output["recommendation"],
            "affected_services": output["affected_services"],
            "timeline": draft["timeline"],
        }
        return report, audit

    async def answer_question(self, investigation_id: str, question: str) -> dict[str, Any]:
        investigation = await self.store.get_investigation(investigation_id)
        if not investigation:
            raise KeyError(investigation_id)
        agents = await self.store.list_agent_states(investigation_id)
        findings = [
            {**{key: finding.get(key) for key in ("finding_id", "timestamp", "source", "message")}, "agent": agent["agent_name"]}
            for agent in agents
            for finding in agent.get("findings", [])
        ]
        if not findings:
            raise ValueError("No investigation evidence is available yet.")
        output, audit = await self.llm.run(
            agent_name="question",
            system_prompt=(
                "Answer only from the supplied investigation evidence. Cite finding_id values exactly. "
                "If the evidence cannot answer the question, set insufficient_evidence to true and explain the gap."
            ),
            user_prompt=json.dumps({"question": question, "evidence": findings}, default=str),
            tools=[],
            response_schema=QuestionOutput,
        )
        valid_ids = {finding.get("finding_id") for finding in findings}
        citations = output["citations"]
        if any(citation not in valid_ids for citation in citations) or (not citations and not output["insufficient_evidence"]):
            raise LLMUnavailable("The answer did not cite valid investigation evidence; retry the question.")
        document = {
            "question_id": str(uuid.uuid4()),
            "investigation_id": investigation_id,
            "question": question,
            "answer": output["answer"],
            "citations": citations,
            "insufficient_evidence": output["insufficient_evidence"],
            "llm_run": audit,
            "created_at": utc_now(),
        }
        await self.store.create_question(document)
        await self.events.publish(investigation_id, {"type": "question_answered", "question": document})
        return document

    @staticmethod
    def _build_report(state: IncidentState, recommendation: str) -> ReportJSON:
        findings = [*state["log_findings"], *state["metrics_findings"], *state["event_findings"]]
        return {
            "summary": state["correlation_summary"],
            "root_cause": state["root_cause"],
            "evidence": {"logs": state["log_findings"], "metrics": state["metrics_findings"], "events": state["event_findings"], "execution": state.get("execution_result")},
            "recommendation": recommendation,
            "affected_services": state["affected_services"],
            "timeline": sorted({(event["time"], event["event"], event["source"]): event for finding in findings for event in finding["raw_data"].get("events", [])}.values(), key=lambda event: event["time"]),
        }

    async def _fail(self, investigation_id: str, exc: Exception) -> None:
        message = "Investigation execution timed out; no recovery is implied" if isinstance(exc, TimeoutError) else str(exc) or type(exc).__name__
        await self.store.invalidate_pending_approvals(investigation_id, "investigation_failed")
        await self._close_unfinished_agents(investigation_id, "failed")
        await self.store.update_investigation(investigation_id, {"status": "failed", "completed_at": utc_now(), "error": message})
        await self.events.publish(investigation_id, {"type": "error", "status": "failed", "message": message})

    async def _close_unfinished_agents(self, investigation_id: str, outcome: str) -> None:
        for agent in await self.store.list_agent_states(investigation_id):
            if agent.get("status") not in {"waiting", "running"}:
                continue
            status = outcome if agent["status"] == "running" else "skipped"
            await self.store.upsert_agent_state(investigation_id, agent["agent_name"], {"status": status, "completed_at": utc_now(), "stop_reason": outcome})
            await self.events.publish(investigation_id, {"type": "agent_status", "agent": agent["agent_name"], "status": status})
