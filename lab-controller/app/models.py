from typing import Any, Literal

from pydantic import BaseModel, Field


Scenario = Literal["redis-unavailable", "database-blocking", "release-regression"]
ActionType = Literal["start_service", "terminate_blocking_session", "rollback_release"]


class RunRequest(BaseModel):
    scenario: Scenario
    ttl_seconds: int = Field(default=900, ge=60, le=900)


class OperationRequest(BaseModel):
    action_id: str = Field(min_length=8, max_length=200)
    investigation_id: str = Field(min_length=8, max_length=200)
    action_type: ActionType
    parameters: dict[str, Any]


class RunCompletionRequest(BaseModel):
    action_id: str
    verification_status: Literal["verified", "unverified"]
    verification: dict[str, Any]
