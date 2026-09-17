from app.models.performance_score import PerformanceScore
from app.models.user import User


def test_list_performance_scores_empty(client):
    resp = client.get("/api/performance-scores")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_performance_scores_filtered_by_user_empty(client):
    resp = client.get("/api/performance-scores", params={"user_id": 1})
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_missing_performance_score_404(client):
    resp = client.get("/api/performance-scores/9999")
    assert resp.status_code == 404


def test_list_performance_scores_returns_seeded_data(client, db_session):
    user = User(name="Perf User", email="perf@example.com")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    score = PerformanceScore(user_id=user.id, period="2026-08", overall_score="88.50")
    db_session.add(score)
    db_session.commit()
    db_session.refresh(score)

    resp = client.get("/api/performance-scores", params={"user_id": user.id})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["period"] == "2026-08"
    assert float(body[0]["overall_score"]) == 88.50

    resp = client.get(f"/api/performance-scores/{score.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == score.id
