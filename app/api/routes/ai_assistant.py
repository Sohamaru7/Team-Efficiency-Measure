from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_manager_or_admin
from app.database.session import get_db
from app.models.enums import AgentActionStatus
from app.models.user import User
from app.schemas.ai_assistant import (
    AgentActionSchema,
    AskAssistantRequest,
    AskAssistantResponse,
    DecideActionResponse,
)
from app.services.ai import AssistantError, ask_assistant
from app.services.ai import approvals

router = APIRouter(prefix="/api/ai", tags=["ai-assistant"])


@router.post("/ask", response_model=AskAssistantResponse)
def ask(
    data: AskAssistantRequest, db: Session = Depends(get_db), current_user: User = Depends(require_manager_or_admin)
) -> AskAssistantResponse:
    """Ask the Manager AI Assistant/Agent a question, or ask it to look into and address a
    problem. Manager/admin only (item 9, "agent tool permissions" — only someone who could
    already see the underlying data may ask the agent to look at it). It answers and acts only
    by calling the fixed tool set in `app.services.ai` — it cannot modify data outside those
    tools, and the four tools that change task/employee data only ever queue a pending action
    for a manager to approve or reject (see the endpoints below) — they never take effect from
    this endpoint alone. See `app.services.ai.assistant` for the full loop.
    """
    try:
        result = ask_assistant(db, data.question)
    except AssistantError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return AskAssistantResponse.model_validate(result)


@router.get("/actions", response_model=list[AgentActionSchema])
def list_actions(
    status_filter: AgentActionStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_admin),
) -> list[AgentActionSchema]:
    """List agent actions (the full audit log), optionally filtered by status. Pass
    `?status=pending` to get exactly the actions awaiting manager approval.
    """
    records = approvals.list_actions(db, status=status_filter, limit=limit)
    return [AgentActionSchema.model_validate(r) for r in records]


@router.post("/actions/{action_id}/approve", response_model=DecideActionResponse)
def approve_action(
    action_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_manager_or_admin)
) -> DecideActionResponse:
    """Approve a pending action. This is the only place a proposed task/employee change from
    the agent actually executes — and it does so through the same validated backend path
    (Pydantic schemas + service functions) the CRUD API uses. `approved_by` is always the real
    authenticated approver, never a caller-supplied id. See `app.services.ai.approvals`.
    """
    result = approvals.decide_action(db, action_id, approve=True, approved_by=current_user.id)
    return _to_response_or_404(result)


@router.post("/actions/{action_id}/reject", response_model=DecideActionResponse)
def reject_action(
    action_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_manager_or_admin)
) -> DecideActionResponse:
    """Reject a pending action. Nothing is executed; the action is recorded as REJECTED."""
    result = approvals.decide_action(db, action_id, approve=False)
    return _to_response_or_404(result)


def _to_response_or_404(result: dict) -> DecideActionResponse:
    if "error" in result:
        detail = result["error"]
        code = status.HTTP_404_NOT_FOUND if "No action with id" in detail else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=detail)
    return DecideActionResponse.model_validate(result)
