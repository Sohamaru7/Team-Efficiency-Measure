"""Tests for the demo-mode auth bypass (scripts/run_demo.py) — GET /api/auth/demo-mode and
POST /api/auth/demo-login. DEMO_MODE defaults to False, so these confirm both states: off by
default (the endpoint behaves as if it doesn't exist) and, when explicitly enabled, that it
issues a real, fully working token without any credentials, without touching the rest of the
auth/authz system (RBAC/rate limiting/expiry/revocation all still apply to that token normally).
"""

from app.core.config import settings
from app.models.enums import UserRole
from app.services.auth_service import DEMO_ACCOUNTS


def test_demo_mode_disabled_by_default():
    assert settings.DEMO_MODE is False


def test_demo_mode_status_reflects_setting(unauthenticated_client, monkeypatch):
    off = unauthenticated_client.get("/api/auth/demo-mode")
    assert off.status_code == 200
    assert off.json() == {"enabled": False}

    monkeypatch.setattr(settings, "DEMO_MODE", True)
    on = unauthenticated_client.get("/api/auth/demo-mode")
    assert on.json() == {"enabled": True}


def test_demo_login_404_when_disabled(unauthenticated_client):
    resp = unauthenticated_client.post("/api/auth/demo-login")
    assert resp.status_code == 404


def test_demo_login_issues_a_working_admin_token_by_default(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)

    resp = unauthenticated_client.post("/api/auth/demo-login")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["role"] == "admin"
    assert body["user"]["email"] == DEMO_ACCOUNTS[UserRole.ADMIN]["email"]

    # The issued token is a completely ordinary one -- it works for a real protected request.
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    me = unauthenticated_client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "admin"


def test_demo_login_can_issue_manager_or_employee_persona(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)

    manager_resp = unauthenticated_client.post("/api/auth/demo-login", json={"role": "manager"})
    assert manager_resp.json()["user"]["role"] == "manager"
    assert manager_resp.json()["user"]["department"] == "Demo Team"

    employee_resp = unauthenticated_client.post("/api/auth/demo-login", json={"role": "employee"})
    assert employee_resp.json()["user"]["role"] == "employee"
    assert employee_resp.json()["user"]["department"] == "Demo Team"


def test_demo_login_reuses_the_same_account_across_calls(unauthenticated_client, monkeypatch, db_session):
    monkeypatch.setattr(settings, "DEMO_MODE", True)

    first = unauthenticated_client.post("/api/auth/demo-login")
    second = unauthenticated_client.post("/api/auth/demo-login")
    assert first.json()["user"]["id"] == second.json()["user"]["id"]


def test_demo_account_still_correctly_bound_by_rbac_when_not_admin(client_as, unauthenticated_client, monkeypatch, db_session):
    """A demo *employee* login is still a real employee -- RBAC itself is not weakened, only
    the login step is; this is what "the rest of auth/authz is untouched" actually means.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", True)

    employee_resp = unauthenticated_client.post("/api/auth/demo-login", json={"role": "employee"})
    headers = {"Authorization": f"Bearer {employee_resp.json()['access_token']}"}

    forbidden = unauthenticated_client.get("/api/dashboard", headers=headers)
    assert forbidden.status_code == 403


def test_demo_login_token_cannot_be_used_after_disabling_demo_mode_is_irrelevant_to_existing_tokens(unauthenticated_client, monkeypatch):
    """Disabling DEMO_MODE only hides the login endpoint going forward -- it must not, and does
    not, retroactively invalidate a token that was already issued (that would require touching
    token verification itself, which this feature deliberately never does).
    """
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    login_resp = unauthenticated_client.post("/api/auth/demo-login")
    token = login_resp.json()["access_token"]

    monkeypatch.setattr(settings, "DEMO_MODE", False)
    resp = unauthenticated_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
