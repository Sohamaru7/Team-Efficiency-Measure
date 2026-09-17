"""API-level tests for POST /api/ai/ask and the Phase 7 action-approval endpoints. The assistant
call itself is monkeypatched at the route module level for /ask so those tests never touch the
network or need an API key. The /actions endpoints are tested against real data — they exercise
the real approval path (`approvals.decide_action`), which is the whole point of Phase 7's
"never bypass backend validation" guarantee.
"""

import app.api.routes.ai_assistant as ai_assistant_route
from app.models.enums import ProjectStatus, UserRole
from app.models.project import Project
from app.models.user import User
from app.services.ai import actions
from app.services.ai.assistant import AssistantAnswer, AssistantError, ToolCallRecord


def _seed(db_session):
    manager = User(name="Manager", email="mgr-api-actions@example.com", role=UserRole.MANAGER, department="Management")
    alice = User(name="Alice API Actions", email="alice-api-actions@example.com", department="Engineering")
    db_session.add_all([manager, alice])
    db_session.commit()
    project = Project(name="API Actions Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    return {"manager": manager, "alice": alice, "project": project}


def test_ask_endpoint_returns_answer_and_tool_calls(client, monkeypatch):
    def fake_ask_assistant(db, question, **kwargs):
        return AssistantAnswer(
            answer="Team efficiency is 82.",
            tool_calls=[ToolCallRecord(name="get_team_metrics", input={}, result={"overall_efficiency_score": 82})],
        )

    monkeypatch.setattr(ai_assistant_route, "ask_assistant", fake_ask_assistant)

    resp = client.post("/api/ai/ask", json={"question": "How is my team doing?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Team efficiency is 82."
    assert body["tool_calls"][0]["name"] == "get_team_metrics"
    assert body["tool_calls"][0]["result"]["overall_efficiency_score"] == 82


def test_ask_endpoint_rejects_empty_question(client):
    resp = client.post("/api/ai/ask", json={"question": ""})
    assert resp.status_code == 422


def test_ask_endpoint_maps_assistant_error_to_503(client, monkeypatch):
    def fake_ask_assistant(db, question, **kwargs):
        raise AssistantError("ANTHROPIC_API_KEY is not configured; the AI assistant is unavailable.")

    monkeypatch.setattr(ai_assistant_route, "ask_assistant", fake_ask_assistant)

    resp = client.post("/api/ai/ask", json={"question": "How is my team doing?"})
    assert resp.status_code == 503
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


def test_ask_endpoint_requires_question_field(client):
    resp = client.post("/api/ai/ask", json={})
    assert resp.status_code == 422


def test_list_actions_filters_by_status(client, db_session):
    seed = _seed(db_session)
    actions.create_task(db_session, project_id=seed["project"].id, title="Pending via API", reason="x")
    actions.send_notification(db_session, employee_id=seed["alice"].id, message="hi", reason="x")

    resp = client.get("/api/ai/actions", params={"status": "pending"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["action"] == "create_task"
    assert body[0]["status"] == "pending"


def test_list_actions_no_filter_returns_everything(client, db_session):
    seed = _seed(db_session)
    actions.create_task(db_session, project_id=seed["project"].id, title="One", reason="x")
    actions.send_notification(db_session, employee_id=seed["alice"].id, message="hi", reason="x")

    resp = client.get("/api/ai/actions")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_approve_action_endpoint_executes_it(client, db_session):
    seed = _seed(db_session)
    proposal = actions.create_task(db_session, project_id=seed["project"].id, title="Approve via API", reason="x")

    resp = client.post(f"/api/ai/actions/{proposal['action_id']}/approve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert "Created task" in body["result"]


def test_reject_action_endpoint(client, db_session):
    seed = _seed(db_session)
    proposal = actions.create_task(db_session, project_id=seed["project"].id, title="Reject via API", reason="x")

    resp = client.post(f"/api/ai/actions/{proposal['action_id']}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_approve_action_404_for_missing_id(client):
    resp = client.post("/api/ai/actions/999999/approve")
    assert resp.status_code == 404


def test_approve_action_409_when_already_decided(client, db_session):
    seed = _seed(db_session)
    proposal = actions.create_task(db_session, project_id=seed["project"].id, title="Twice", reason="x")
    client.post(f"/api/ai/actions/{proposal['action_id']}/approve")

    resp = client.post(f"/api/ai/actions/{proposal['action_id']}/approve")
    assert resp.status_code == 409
