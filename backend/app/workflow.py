from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import timedelta
from typing import Any, Literal

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import var_child_runnable_config
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, interrupt

from .config import Settings
from .events import EventHub
from .llm import LLMClient
from .models import Finding, IncidentState, ReportJSON, utc_iso, utc_now
from .store import Store
from .tools import build_timeline, format_report, generate_root_cause, query_loki, query_prometheus, rank_hypotheses


SCENARIO_PROFILES: dict[str, dict[str, Any]] = {
    "redis-failure": {
        "log_query": '{service=~"api-server|payment-service"} |~ "Redis|redis|connection"',
        "metric_query": 'sum(rate(http_requests_total{status="500"}[1m]))',
        "log_message": "Redis connection timeouts appear across both dependent services.",
        "metric_message": "HTTP 500 rate increased while successful Redis connections dropped.",
        "event_message": "Redis failure preceded dependent API and payment errors.",
        "root_cause": "Redis unavailability exhausted connection attempts and caused dependent requests to fail.",
        "summary": "The incident was caused by Redis becoming unavailable to the API and payment services.",
        "affected": ["api-server", "payment-service", "redis"],
        "action_type": "restart_service",
        "target": "redis",
        "recommendation": "Restore Redis availability, then verify dependent request success and connection metrics.",
    },
    "slow-db": {
        "log_query": '{service="api-server"} |~ "SELECT|8000ms|slow"',
        "metric_query": "histogram_quantile(0.95, sum(rate(postgres_query_duration_seconds_bucket[1m])) by (le))",
        "log_message": "API logs show user queries taking approximately 8 seconds.",
        "metric_message": "PostgreSQL query and HTTP request p95 latency spiked together.",
        "event_message": "The database latency increase preceded slow API responses.",
        "root_cause": "Database query latency saturated the API request path.",
        "summary": "A simulated slow PostgreSQL query raised API latency to approximately eight seconds.",
        "affected": ["api-server", "postgres"],
        "action_type": "disable_failure_mode",
        "target": "api-server:slow-db",
        "recommendation": "Disable the slow-query mode and verify database and request p95 latency return to baseline.",
    },
    "bad-deployment": {
        "log_query": '{service=~"api-server|payment-service"} |~ "v2|Internal server error|deployment"',
        "metric_query": 'sum(rate(http_requests_total{status="500"}[1m])) / sum(rate(http_requests_total[1m]))',
        "log_message": "Version v2 emits internal server errors on normal request paths.",
        "metric_message": "The HTTP 500 ratio increased sharply after v2 became active.",
        "event_message": "The v2 deployment immediately preceded the error-rate increase.",
        "root_cause": "The v2 deployment introduced a high rate of HTTP 500 responses.",
        "summary": "A deliberately broken v2 deployment caused widespread HTTP 500 responses.",
        "affected": ["api-server", "payment-service"],
        "action_type": "rollback_deployment",
        "target": "sample-services:v2-to-v1",
        "recommendation": "Roll both sample services back to v1 and verify the HTTP 500 ratio returns to baseline.",
    },
}


class InvestigationWorkflow:
    def __init__(self, store: Store, events: EventHub, settings: Settings, checkpointer: Any | None = None) -> None:
        self.store = store
        self.events = events
        self.settings = settings
        self.llm = LLMClient(settings)
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
        builder.add_edge("correlation", "approval")
        builder.add_edge("approval", "record_decision")
        builder.add_conditional_edges("record_decision", self._route_approval, {"approved": "execute", "rejected": "rejected"})
        builder.add_edge("execute", "report")
        builder.add_edge("report", END)
        builder.add_edge("rejected", END)
        return builder.compile(checkpointer=checkpointer)

    async def create(self, investigation_id: str, scenario: str) -> None:
        now = utc_now()
        await self.store.create_investigation(
            {
                "incident_id": investigation_id,
                "scenario": scenario,
                "status": "investigating",
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
                "report_json": {},
                "report_markdown": "",
            }
        )
        for name in ("log", "metrics", "event", "correlation", "report"):
            await self.store.upsert_agent_state(
                investigation_id,
                name,
                {"findings": [], "steps": [], "status": "waiting", "started_at": None, "completed_at": None},
            )

    def start(self, investigation_id: str, scenario: str) -> None:
        self.tasks[investigation_id] = asyncio.create_task(self._run_initial(investigation_id, scenario))

    async def _run_initial(self, investigation_id: str, scenario: str) -> None:
        try:
            if self.settings.simulation_warmup_seconds:
                await asyncio.sleep(self.settings.simulation_warmup_seconds)
            state: IncidentState = {
                "incident_id": investigation_id,
                "scenario": scenario,
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

    async def resume(self, investigation_id: str, approved: bool) -> None:
        try:
            await asyncio.wait_for(
                self.graph.ainvoke(Command(resume=approved), config=self._config(investigation_id)), timeout=300
            )
        except Exception as exc:
            await self._fail(investigation_id, exc)

    async def cancel(self, investigation_id: str) -> None:
        task = self.tasks.get(investigation_id)
        if task and not task.done():
            task.cancel()
        await self.store.update_investigation(investigation_id, {"status": "cancelled", "completed_at": utc_now()})
        await self.events.publish(investigation_id, {"type": "investigation", "status": "cancelled"})

    @staticmethod
    def _config(investigation_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": investigation_id}}

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

    async def _log_agent(self, state: IncidentState) -> dict[str, Any]:
        profile = SCENARIO_PROFILES[state["scenario"]]
        await self._agent_step(state["incident_id"], "log", "Thought: inspect recent error streams for a shared failure signature")
        await self._agent_step(state["incident_id"], "log", f"Action: query Loki with {profile['log_query']}")
        response = await asyncio.to_thread(
            query_loki.invoke,
            {"query": profile["log_query"], "time_from": "now-5m", "time_to": "now"},
        )
        finding: Finding = {"timestamp": utc_iso(), "source": "loki", "message": profile["log_message"], "raw_data": response}
        await self._agent_step(state["incident_id"], "log", f"Observation: {profile['log_message']}")
        await self._complete_agent(state["incident_id"], "log", [finding])
        return {"log_findings": [finding], "agent_steps": [{"agent": "log", "step": "Result: log evidence captured"}]}

    async def _metrics_agent(self, state: IncidentState) -> dict[str, Any]:
        profile = SCENARIO_PROFILES[state["scenario"]]
        await self._agent_step(state["incident_id"], "metrics", "Thought: compare current service indicators with the healthy baseline")
        await self._agent_step(state["incident_id"], "metrics", f"Action: query Prometheus with {profile['metric_query']}")
        response = await asyncio.to_thread(
            query_prometheus.invoke,
            {"query": profile["metric_query"], "time_from": "now-5m", "time_to": "now"},
        )
        finding: Finding = {"timestamp": utc_iso(), "source": "prometheus", "message": profile["metric_message"], "raw_data": response}
        await self._agent_step(state["incident_id"], "metrics", f"Observation: {profile['metric_message']}")
        await self._complete_agent(state["incident_id"], "metrics", [finding])
        return {"metrics_findings": [finding], "agent_steps": [{"agent": "metrics", "step": "Result: metric evidence captured"}]}

    async def _event_agent(self, state: IncidentState) -> dict[str, Any]:
        profile = SCENARIO_PROFILES[state["scenario"]]
        await self._agent_step(state["incident_id"], "event", "Thought: order changes and symptoms to test temporal causality")
        now = utc_now()
        raw_events = [
            {"timestamp": (now - timedelta(seconds=20)).isoformat(), "message": f"Scenario {state['scenario']} activated", "source": "simulator", "severity": "warning"},
            {"timestamp": now.isoformat(), "message": profile["event_message"], "source": "event-agent", "severity": "error"},
        ]
        timeline = build_timeline.invoke({"events": raw_events})
        finding: Finding = {"timestamp": utc_iso(), "source": "event-stream", "message": profile["event_message"], "raw_data": timeline}
        await self._agent_step(state["incident_id"], "event", f"Observation: {profile['event_message']}")
        await self._complete_agent(state["incident_id"], "event", [finding])
        return {"event_findings": [finding], "agent_steps": [{"agent": "event", "step": "Result: incident timeline built"}]}

    async def _correlation_agent(self, state: IncidentState) -> dict[str, Any]:
        incident_id = state["incident_id"]
        profile = SCENARIO_PROFILES[state["scenario"]]
        await self._agent_step(incident_id, "correlation", "Thought: test competing hypotheses against all three evidence streams")
        evidence = {"logs": state["log_findings"], "metrics": state["metrics_findings"], "events": state["event_findings"]}
        hypotheses = [
            "Redis dependency failure",
            "Database query overload",
            "Bad v2 deployment",
            "Transient network degradation",
        ]
        ranked = rank_hypotheses.invoke({"hypotheses": hypotheses, "evidence": evidence})
        generated = generate_root_cause.invoke({"evidence": {**evidence, "scenario": state["scenario"]}})
        fallback = profile["root_cause"]
        root_cause = await self.llm.complete(
            "State one concise root cause from this evidence. Do not propose an action.\n" + json.dumps(evidence, default=str),
            fallback,
        )
        summary = f"{profile['summary']} Cross-agent evidence converged on one causal chain."
        approval_id = str(uuid.uuid4())
        approval = {
            "approval_id": approval_id,
            "action_type": profile["action_type"],
            "target": profile["target"],
            "reason": root_cause,
            "evidence": {**evidence, "hypotheses": ranked["data"], "synthesis": generated["data"]},
            "proposed_by": "correlation",
            "proposed_at": utc_iso(),
        }
        await self.store.create_approval(
            {**approval, "investigation_id": incident_id, "status": "pending", "created_at": utc_now(), "decided_at": None}
        )
        await self._agent_step(incident_id, "correlation", f"Result: {root_cause}")
        await self._complete_agent(
            incident_id,
            "correlation",
            [{"timestamp": utc_iso(), "source": "cross-agent", "message": root_cause, "raw_data": approval["evidence"]}],
        )
        await self.events.publish(incident_id, {"type": "approval", "approval": approval, "status": "pending"})
        return {
            "correlation_summary": summary,
            "root_cause": root_cause,
            "affected_services": profile["affected"],
            "pending_approval": approval,
            "status": "awaiting_approval",
            "agent_steps": [{"agent": "correlation", "step": "Action: request human approval for remediation"}],
        }

    def _approval_node(self, state: IncidentState, config: RunnableConfig) -> dict[str, Any]:
        """Pure interrupt gate; side effects live in the following node for resume safety."""
        # LangGraph documents async context propagation as Python 3.11+.
        # CI may run 3.10, where a sync node executed by ainvoke loses the contextvar.
        token = var_child_runnable_config.set(config) if sys.version_info < (3, 11) else None
        try:
            approved = interrupt(state["pending_approval"])
        finally:
            if token is not None:
                var_child_runnable_config.reset(token)
        decision = "approved" if approved else "rejected"
        return {"approval_result": decision, "status": "investigating" if approved else "completed_with_rejection"}

    async def _record_approval_decision(self, state: IncidentState) -> dict[str, Any]:
        decision = state["approval_result"]
        approved = decision == "approved"
        approval = state["pending_approval"]
        assert approval is not None
        await self.store.update_approval(approval["approval_id"], {"status": decision, "decided_at": utc_now()})
        await self.store.update_investigation(state["incident_id"], {"status": "investigating" if approved else "completed_with_rejection"})
        await self.events.publish(state["incident_id"], {"type": "approval", "approval_id": approval["approval_id"], "status": decision})
        return {}

    @staticmethod
    def _route_approval(state: IncidentState) -> Literal["approved", "rejected"]:
        return "approved" if state["approval_result"] == "approved" else "rejected"

    async def _execute_remediation(self, state: IncidentState) -> dict[str, Any]:
        await self.events.publish(state["incident_id"], {"type": "remediation", "status": "running"})
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if state["scenario"] == "redis-failure":
                    payload, path = {"enabled": False}, "/api/simulate/redis-failure"
                elif state["scenario"] == "slow-db":
                    payload, path = {"enabled": False}, "/api/simulate/slow-db"
                else:
                    payload, path = {"version": "v1"}, "/api/simulate/bad-deployment"
                targets = [self.settings.sample_api_url]
                if state["scenario"] != "slow-db":
                    targets.append(self.settings.sample_payment_url)
                responses = await asyncio.gather(*(client.post(f"{target}{path}", json=payload) for target in targets))
                for response in responses:
                    response.raise_for_status()
                result = {"status": "success", "targets": targets, "action": path}
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}
        await self.events.publish(state["incident_id"], {"type": "remediation", **result})
        return {"execution_result": result}

    async def _report_agent(self, state: IncidentState) -> dict[str, Any]:
        profile = SCENARIO_PROFILES[state["scenario"]]
        await self._agent_step(state["incident_id"], "report", "Thought: preserve the conclusion, evidence, action, and timeline")
        report = self._build_report(state, profile["recommendation"])
        markdown = format_report.invoke({"data": report, "format": "markdown"})["data"]["report"]
        await self._complete_agent(
            state["incident_id"], "report", [{"timestamp": utc_iso(), "source": "report", "message": report["summary"], "raw_data": report}]
        )
        await self.store.update_investigation(
            state["incident_id"],
            {"status": "completed", "completed_at": utc_now(), "report_json": report, "report_markdown": markdown},
        )
        await self.events.publish(state["incident_id"], {"type": "investigation", "status": "completed", "report": report})
        return {"report_json": report, "report_markdown": markdown, "status": "completed", "pending_approval": None}

    async def _rejected_report(self, state: IncidentState) -> dict[str, Any]:
        await self._agent_step(state["incident_id"], "report", "Result: remediation rejected; close without executing an action")
        report = self._build_report(state, "Remediation was rejected by the operator; no operational action was executed.")
        markdown = format_report.invoke({"data": report, "format": "markdown"})["data"]["report"]
        await self._complete_agent(
            state["incident_id"], "report", [{"timestamp": utc_iso(), "source": "report", "message": report["summary"], "raw_data": report}]
        )
        await self.store.update_investigation(
            state["incident_id"],
            {"status": "completed_with_rejection", "completed_at": utc_now(), "report_json": report, "report_markdown": markdown},
        )
        await self.events.publish(state["incident_id"], {"type": "investigation", "status": "completed_with_rejection", "report": report})
        return {"report_json": report, "report_markdown": markdown, "status": "completed_with_rejection", "pending_approval": None}

    @staticmethod
    def _build_report(state: IncidentState, recommendation: str) -> ReportJSON:
        findings = [*state["log_findings"], *state["metrics_findings"], *state["event_findings"]]
        return {
            "summary": state["correlation_summary"],
            "root_cause": state["root_cause"],
            "evidence": {"logs": state["log_findings"], "metrics": state["metrics_findings"], "events": state["event_findings"], "execution": state.get("execution_result")},
            "recommendation": recommendation,
            "affected_services": state["affected_services"],
            "timeline": [{"time": finding["timestamp"], "event": finding["message"], "source": finding["source"]} for finding in sorted(findings, key=lambda item: item["timestamp"])],
        }

    async def _fail(self, investigation_id: str, exc: Exception) -> None:
        await self.store.update_investigation(investigation_id, {"status": "failed", "completed_at": utc_now(), "error": str(exc)})
        await self.events.publish(investigation_id, {"type": "error", "status": "failed", "message": str(exc)})
