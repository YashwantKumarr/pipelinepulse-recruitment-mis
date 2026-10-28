from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.main import create_app
from tests.conftest import WEBHOOK_SECRET


def test_health_reports_ok_and_versions(client):
    body = client.get("/health").json()
    assert client.get("/health").status_code == 200
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["ai_provider"] == "rules"
    assert body["assessment_version"] == "fitment-v1.0.0"


def test_index_served_with_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "TalentFlow AI" in response.text
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_api_documentation_is_available(client):
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/api/jobs" in schema["paths"]
    assert "/api/webhooks/n8n/candidate-event" in schema["paths"]


def test_unknown_route_uses_error_envelope(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_sqlite_foreign_keys_are_enforced(app):
    engine = app.state.engine
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        try:
            connection.execute(
                text(
                    "INSERT INTO assessments (candidate_id, job_id, assessment_version, provider, ai_status, "
                    "summary_source, summary, criteria, ai_disagreements, review_status, created_at) "
                    "VALUES (999, 999, 'v', 'rules', 'disabled', 'rules', 's', '[]', '[]', 'pending_review', "
                    "'2026-01-01 00:00:00')"
                )
            )
            connection.commit()
            raised = False
        except IntegrityError:
            raised = True
    assert raised, "orphan assessment insert should violate the foreign key"


def test_data_persists_across_application_restarts(settings, clock, make_job):
    first = create_app(settings=settings, clock=clock)
    from fastapi.testclient import TestClient

    with TestClient(first) as client:
        job_id = client.post("/api/jobs", json={"title": "Persisted", "requirements": ["Go"]}).json()["id"]

    second = create_app(settings=settings, clock=clock)
    with TestClient(second) as client:
        assert client.get(f"/api/jobs/{job_id}").json()["title"] == "Persisted"


def test_webhook_secret_is_not_exposed_in_settings_repr(settings):
    assert WEBHOOK_SECRET not in repr(settings)
    assert isinstance(settings, Settings)
