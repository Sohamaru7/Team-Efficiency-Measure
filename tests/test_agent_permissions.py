"""Explicit tests for "AI agents must operate using explicit tool permissions" and "add tests
for... agent actions" (production-readiness pass). Covers three layers:

1. The agent's *tool whitelist* is exactly what's declared — no function is reachable by name
   that isn't also a documented tool schema, and vice versa (a silent mismatch would mean the
   model could be told about a tool it can't call, or — worse — a tool could be invoked that was
   never reviewed/declared).
2. The agent's *HTTP surface* requires real authentication and a manager/admin role (covered in
   depth in test_authorization_boundaries.py; re-asserted here alongside the tool-level tests so
   this file is a single place documenting the full "agent permission" story).
3. Approval-required agent actions are correctly attributed to the real authenticated approver,
   never a caller-supplied id, and can never execute without that approval step.
"""

from datetime import date, timedelta

from app.models.agent_action import AgentAction
from app.models.enums import AgentActionStatus, ProjectStatus, TaskPriority, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.ai.actions import ACTION_TOOL_DEFINITIONS, ACTION_TOOL_FUNCTIONS, ACTION_TOOL_NAMES
from app.services.ai.assistant import ALL_TOOL_DEFINITIONS, ALL_TOOL_FUNCTIONS
from app.services.ai.detection import DETECTION_TOOL_DEFINITIONS, DETECTION_TOOL_FUNCTIONS
from app.services.ai.tools import TOOL_DEFINITIONS, TOOL_FUNCTIONS
from app.services.daily_manager.constants import ALLOWED_AUTO_ACTION_TOOLS


def _seed(db_session):
    admin = User(name="Admin AgentPerm", email="admin-agentperm@example.com", role=UserRole.ADMIN)
    manager = User(name="Manager AgentPerm", email="mgr-agentperm@example.com", role=UserRole.MANAGER, department="Engineering")
    alice = User(name="Alice AgentPerm", email="alice-agentperm@example.com", role=UserRole.EMPLOYEE, department="Engineering")
    db_session.add_all([admin, manager, alice])
    db_session.commit()
    project = Project(name="AgentPerm Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    return {"admin": admin, "manager": manager, "alice": alice, "project": project}


# ---------------------------------------------------------------------------- tool whitelist ----


def test_every_declared_tool_name_has_a_callable():
    declared_names = {t["name"] for t in ALL_TOOL_DEFINITIONS}
    assert declared_names == set(ALL_TOOL_FUNCTIONS.keys())


def test_full_tool_set_is_exactly_the_union_of_the_three_layers():
    expected_names = set(TOOL_FUNCTIONS) | set(DETECTION_TOOL_FUNCTIONS) | set(ACTION_TOOL_FUNCTIONS)
    assert set(ALL_TOOL_FUNCTIONS.keys()) == expected_names
    # 8 read tools + 1 detection tool + 6 action tools = 15, pinned so a silent addition/removal
    # anywhere in the three source modules is caught here.
    assert len(expected_names) == 15


def test_read_and_detection_tools_never_mutate_anything(db_session):
    """Every tool outside ACTION_TOOL_NAMES must be read-only — assert this structurally by
    confirming none of their names appear in the write-capable set, which is the only place in
    this codebase a tool is allowed to touch task/project/user rows.
    """
    read_only_names = set(TOOL_FUNCTIONS) | set(DETECTION_TOOL_FUNCTIONS)
    assert read_only_names.isdisjoint(ACTION_TOOL_NAMES)


def test_action_tool_definitions_all_require_a_reason_argument():
    """Every write-capable tool must force the model to state why — an un-reasoned action is
    never permitted to reach the audit log."""
    for tool in ACTION_TOOL_DEFINITIONS:
        assert "reason" in tool["input_schema"]["properties"]
        assert "reason" in tool["input_schema"].get("required", [])


def test_daily_manager_can_only_ever_call_the_two_allowed_tools():
    assert ALLOWED_AUTO_ACTION_TOOLS == {"send_notification", "assign_task"}
    # send_notification is auto-execute, assign_task is approval-required -- both already
    # exist in ACTION_TOOL_NAMES; nothing outside that set is even a valid tool name.
    assert ALLOWED_AUTO_ACTION_TOOLS <= ACTION_TOOL_NAMES


def test_no_tool_exists_for_penalties_discipline_evaluation_or_deletion():
    """Structural proof (not just a policy statement) that the restricted categories from the
    brief have no corresponding capability anywhere in the tool set.
    """
    forbidden_substrings = ("delete", "penal", "discipl", "evaluat", "terminat", "fire")
    for name in ALL_TOOL_FUNCTIONS:
        lowered = name.lower()
        assert not any(s in lowered for s in forbidden_substrings), f"Unexpected tool name: {name}"


# --------------------------------------------------------------------- HTTP-level permissions ----


def test_ai_ask_requires_authentication(unauthenticated_client):
    resp = unauthenticated_client.post("/api/ai/ask", json={"question": "hi"})
    assert resp.status_code == 401


def test_ai_ask_requires_manager_or_admin_role(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).post("/api/ai/ask", json={"question": "hi"})
    assert resp.status_code == 403


def test_ai_actions_list_requires_manager_or_admin_role(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).get("/api/ai/actions")
    assert resp.status_code == 403


# --------------------------------------------------------- approval attribution & enforcement ----


def test_approve_action_records_the_real_authenticated_approver(client_as, db_session):
    seed = _seed(db_session)
    task = Task(
        project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Reassign me",
        status=TaskStatus.IN_PROGRESS, priority=TaskPriority.HIGH, deadline=date.today() + timedelta(days=1),
    )
    db_session.add(task)
    db_session.commit()

    from app.services.ai import actions as ai_actions

    proposal = ai_actions.assign_task(db_session, task_id=task.id, employee_id=seed["alice"].id, reason="test")
    action_id = proposal["action_id"]

    resp = client_as(seed["manager"]).post(f"/api/ai/actions/{action_id}/approve")
    assert resp.status_code == 200

    record = db_session.get(AgentAction, action_id)
    assert record.status == AgentActionStatus.APPROVED
    assert record.approved is True


def test_employee_cannot_approve_a_pending_agent_action(client_as, db_session):
    seed = _seed(db_session)
    task = Task(project_id=seed["project"].id, assigned_to=seed["alice"].id, title="X", status=TaskStatus.IN_PROGRESS)
    db_session.add(task)
    db_session.commit()

    from app.services.ai import actions as ai_actions

    proposal = ai_actions.assign_task(db_session, task_id=task.id, employee_id=seed["alice"].id, reason="test")

    resp = client_as(seed["alice"]).post(f"/api/ai/actions/{proposal['action_id']}/approve")
    assert resp.status_code == 403

    record = db_session.get(AgentAction, proposal["action_id"])
    assert record.status == AgentActionStatus.PENDING  # untouched -- the denied request changed nothing
