"""Tests for app.core.security (pure hashing/JWT primitives) and the /api/auth/* endpoints
(login, logout/token revocation, /me, change-password). Uses `unauthenticated_client` where the
real bearer-token verification path matters — `client`'s default admin override would otherwise
mask exactly the behavior these tests exist to check.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import (
    InvalidTokenError,
    PasswordTooLongError,
    create_access_token,
    decode_access_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.models.enums import UserRole
from app.models.user import User


# --------------------------------------------------------------------------- password hashing ----


def test_hash_password_is_not_plaintext():
    hashed = hash_password("correcthorse1")
    assert hashed != "correcthorse1"
    assert hashed.startswith("$2b$")  # bcrypt hash prefix


def test_verify_password_correct_and_incorrect():
    hashed = hash_password("correcthorse1")
    assert verify_password("correcthorse1", hashed) is True
    assert verify_password("wrongpassword", hashed) is False


def test_verify_password_against_none_is_false():
    assert verify_password("anything", None) is False


def test_hash_password_rejects_over_72_bytes():
    with pytest.raises(PasswordTooLongError):
        hash_password("x" * 73)


def test_password_strength_rules():
    with pytest.raises(ValueError):
        validate_password_strength("short1")  # too short
    with pytest.raises(ValueError):
        validate_password_strength("alllettersnodigits")  # no digit
    with pytest.raises(ValueError):
        validate_password_strength("12345678")  # no letter
    validate_password_strength("correcthorse1")  # does not raise


# ------------------------------------------------------------------------------------- JWTs ----


def test_create_and_decode_access_token_roundtrip():
    token, jti, expires_at = create_access_token(42, "manager")
    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "manager"
    assert payload["jti"] == jti
    assert expires_at > datetime.now(timezone.utc)


def test_decode_garbage_token_raises():
    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-real-token")


def test_decode_tampered_token_raises():
    token, _jti, _exp = create_access_token(1, "employee")
    tampered = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")
    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)


def test_decode_expired_token_raises(monkeypatch):
    import app.core.security as security_module

    original_expire = security_module.settings.ACCESS_TOKEN_EXPIRE_MINUTES
    monkeypatch.setattr(security_module.settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    try:
        token, _jti, _exp = create_access_token(1, "employee")
    finally:
        monkeypatch.setattr(security_module.settings, "ACCESS_TOKEN_EXPIRE_MINUTES", original_expire)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


# ----------------------------------------------------------------------------- /api/auth/* ----


def _seed_user(db_session, email="alice-auth@example.com", password="correcthorse1", role=UserRole.EMPLOYEE, active=True):
    user = User(name="Alice Auth", email=email, role=role, department="Engineering", active=active, hashed_password=hash_password(password))
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_login_success_returns_token_and_user(unauthenticated_client, db_session):
    _seed_user(db_session)
    resp = unauthenticated_client.post("/api/auth/login", json={"email": "alice-auth@example.com", "password": "correcthorse1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "alice-auth@example.com"
    assert "hashed_password" not in body["user"]
    assert "password" not in body["user"]


def test_login_wrong_password_401(unauthenticated_client, db_session):
    _seed_user(db_session)
    resp = unauthenticated_client.post("/api/auth/login", json={"email": "alice-auth@example.com", "password": "wrongpassword"})
    assert resp.status_code == 401


def test_login_unknown_email_401(unauthenticated_client, db_session):
    resp = unauthenticated_client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    assert resp.status_code == 401


def test_login_unknown_and_wrong_password_give_the_same_generic_message(unauthenticated_client, db_session):
    """No user-enumeration signal: both failure modes must be indistinguishable to the client."""
    _seed_user(db_session)
    wrong_password = unauthenticated_client.post("/api/auth/login", json={"email": "alice-auth@example.com", "password": "wrongpassword"})
    unknown_email = unauthenticated_client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


def test_login_inactive_account_401(unauthenticated_client, db_session):
    _seed_user(db_session, active=False)
    resp = unauthenticated_client.post("/api/auth/login", json={"email": "alice-auth@example.com", "password": "correcthorse1"})
    assert resp.status_code == 401


def test_login_user_with_no_password_set_401(unauthenticated_client, db_session):
    user = User(name="No Password", email="nopass@example.com", role=UserRole.EMPLOYEE, active=True)
    db_session.add(user)
    db_session.commit()
    resp = unauthenticated_client.post("/api/auth/login", json={"email": "nopass@example.com", "password": "anything123"})
    assert resp.status_code == 401


def test_protected_endpoint_without_token_401(unauthenticated_client):
    resp = unauthenticated_client.get("/api/auth/me")
    assert resp.status_code == 401


def test_protected_endpoint_with_garbage_token_401(unauthenticated_client):
    resp = unauthenticated_client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_me_returns_current_user(unauthenticated_client, db_session):
    _seed_user(db_session)
    login = unauthenticated_client.post("/api/auth/login", json={"email": "alice-auth@example.com", "password": "correcthorse1"})
    token = login.json()["access_token"]
    resp = unauthenticated_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice-auth@example.com"


def test_logout_revokes_token_immediately(unauthenticated_client, db_session):
    _seed_user(db_session)
    login = unauthenticated_client.post("/api/auth/login", json={"email": "alice-auth@example.com", "password": "correcthorse1"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    still_valid = unauthenticated_client.get("/api/auth/me", headers=headers)
    assert still_valid.status_code == 200

    logout_resp = unauthenticated_client.post("/api/auth/logout", headers=headers)
    assert logout_resp.status_code == 204

    after_logout = unauthenticated_client.get("/api/auth/me", headers=headers)
    assert after_logout.status_code == 401


def test_change_password_requires_correct_current_password(unauthenticated_client, db_session):
    _seed_user(db_session)
    login = unauthenticated_client.post("/api/auth/login", json={"email": "alice-auth@example.com", "password": "correcthorse1"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    denied = unauthenticated_client.post(
        "/api/auth/change-password", headers=headers, json={"current_password": "wrongpassword", "new_password": "newpassword1"}
    )
    assert denied.status_code == 401

    ok = unauthenticated_client.post(
        "/api/auth/change-password", headers=headers, json={"current_password": "correcthorse1", "new_password": "newpassword1"}
    )
    assert ok.status_code == 204

    relogin_old = unauthenticated_client.post("/api/auth/login", json={"email": "alice-auth@example.com", "password": "correcthorse1"})
    assert relogin_old.status_code == 401
    relogin_new = unauthenticated_client.post("/api/auth/login", json={"email": "alice-auth@example.com", "password": "newpassword1"})
    assert relogin_new.status_code == 200


def test_login_rate_limited_after_repeated_attempts(unauthenticated_client, db_session):
    _seed_user(db_session)
    responses = [
        unauthenticated_client.post("/api/auth/login", json={"email": "alice-auth@example.com", "password": "wrongpassword"})
        for _ in range(15)
    ]
    assert any(r.status_code == 429 for r in responses)
