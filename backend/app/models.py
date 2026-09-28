from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, TypedDict

from typing_extensions import NotRequired

from pydantic import BaseModel, Field


Scenario = Literal["redis-unavailable", "database-blocking", "release-regression"]
AgentName = Literal["log", "metrics", "event", "correlation", "report"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


class Finding(TypedDict):
    finding_id: NotRequired[str]
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
    services: list[str]
    symptom: str
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
    observation_start: NotRequired[str]
    observation_end: NotRequired[str]
    recommendation: NotRequired[str]
    insufficient_evidence: NotRequired[bool]
    assessment: NotRequired[str]
    lab_run_id: NotRequired[str | None]


class InvestigationRequest(BaseModel):
    services: list[Literal["api-server", "payment-service"]] = Field(min_length=1)
    symptom: str = Field(min_length=3, max_length=500)
    time_from: datetime | None = None
    time_to: datetime | None = None
    auto_start_investigation: bool = True


class LabRunRequest(BaseModel):
    scenario: Scenario
    auto_start_investigation: bool = True
    ttl_seconds: int = Field(default=900, ge=60, le=900)


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]


class AgentFindingOutput(BaseModel):
    finding: str = Field(description="A concise evidence-backed finding")
    insufficient_evidence: bool = Field(description="True if the observations do not support a diagnosis")


class ProposedAction(BaseModel):
    action_type: Literal["start_service", "terminate_blocking_session", "rollback_release"]
    resource_id: str
    expected_container_id: str | None = None
    expected_current_image_id: str | None = None
    previous_image_id: str | None = None
    database: str | None = None
    pid: int | None = None
    backend_start: str | None = None
    supporting_finding_ids: list[str] = Field(min_length=1)
    supporting_observation_ids: list[str] = Field(min_length=1)


class Hypothesis(BaseModel):
    explanation: str
    supporting_finding_ids: list[str]
    limitations: str


class CorrelationOutput(BaseModel):
    root_cause: str = Field(description="The most likely root cause supported by the evidence")
    summary: str = Field(description="A concise synthesis of the cross-agent evidence")
    affected_services: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=2)
    insufficient_evidence: bool
    recommendation: str
    proposed_action: ProposedAction | None
    assessment: Literal["incident_detected", "no_incident_observed", "insufficient_evidence"]


class ReportOutput(BaseModel):
    summary: str
    root_cause: str
    recommendation: str
    affected_services: list[str]


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class QuestionOutput(BaseModel):
    answer: str = Field(description="An answer grounded only in the supplied investigation evidence")
    citations: list[str] = Field(default_factory=list, description="Finding IDs supporting the answer")
    insufficient_evidence: bool = False
