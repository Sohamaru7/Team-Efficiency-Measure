from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AgentActionStatus


class AskAssistantRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ToolCallSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    input: dict[str, Any]
    result: Any


class AskAssistantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    answer: str
    tool_calls: list[ToolCallSchema]


class AgentActionSchema(BaseModel):
    """One row of the agent_actions audit log (Phase 2 schema, Phase 7 fields)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_type: str
    action: str
    target: Optional[str] = None
    reason: Optional[str] = None
    timestamp: datetime
    status: AgentActionStatus
    approved: bool
    result: Optional[str] = None


class DecideActionResponse(BaseModel):
    action_id: int
    status: str
    result: Optional[str] = None
