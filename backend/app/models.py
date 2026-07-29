from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, TypedDict

from typing_extensions import NotRequired

from pydantic import BaseModel, Field


Scenario = Literal["redis-failure", "slow-db", "bad-deployment"]
AgentName = Literal["log", "metrics", "event", "correlation", "report"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


class Finding(TypedDict):
    timestamp: str
    source: str
    message: str
    raw_data: dict[str, Any]


class AgentStep(TypedDict):
    agent: str
    step: str


class ApprovalRequest(TypedDict):
    approval_id: str
    action_type: str
    target: str
    reason: str
    evidence: dict[str, Any]
    proposed_by: str
    proposed_at: str


class ReportJSON(TypedDict):
    summary: str
    root_cause: str
    evidence: dict[str, Any]
    recommendation: str
    affected_services: list[str]
    timeline: list[dict[str, Any]]


class IncidentState(TypedDict):
    incident_id: str
    scenario: str
    log_findings: Annotated[list[Finding], operator.add]
    metrics_findings: Annotated[list[Finding], operator.add]
    event_findings: Annotated[list[Finding], operator.add]
    correlation_summary: str
    root_cause: str
    affected_services: list[str]
    report_json: ReportJSON
    report_markdown: str
    pending_approval: ApprovalRequest | None
    approval_result: str
    agent_steps: Annotated[list[AgentStep], operator.add]
    status: str
    execution_result: NotRequired[dict[str, Any]]


class SimulationRequest(BaseModel):
    auto_start_investigation: bool = True


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]


class SettingsUpdate(BaseModel):
    llm_provider: Literal["deterministic", "openai", "gemini"]
    api_key: str = Field(default="", max_length=500)
