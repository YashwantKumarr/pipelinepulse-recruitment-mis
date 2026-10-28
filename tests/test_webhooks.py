from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import AuditEvent, WorkflowRun
from tests.conftest import FIXED_NOW, WEBHOOK_HEADERS


def _event(**overrides):
    body = {
        "event_id": "evt-20260301-0001",
        "event_type": "candidate.created",
        "candidate_id": 1,
        "occurred_at": "2026-03-01T09:00:00+00:00",
    }
    body.update(overrides)
    return body


@pytest.fixture
def seeded(client, upload, make_job):
    candidate = upload("cv.txt", b"Python and SQL in production", name="Hook Person").json()
    job = make_job(requirements=["Python", "Airflow"])
    return candidate["id"], job["id"]


def test_endpoint_is_hidden_when_webhooks_disabled(settings, clock):
    disabled = replace(settings, enable_n8n_webhooks=False, n8n_shared_secret="")
    app = create_app(settings=disabled, clock=clock)
    with TestClient(app) as client:
        response = client.post("/api/webhooks/n8n/candidate-event", json=_event(), headers=WEBHOOK_HEADERS)
    assert response.status_code == 404


def test_missing_or_wrong_secret_is_unauthorised(client):
    assert client.post("/api/webhooks/n8n/candidate-event", json=_event()).status_code == 401
    wrong = {"X-N8N-Secret": "wrong-secret-value-000"}
    assert client.post("/api/webhooks/n8n/candidate-event", json=_event(), headers=wrong).status_code == 401


def test_unauthorised_request_records_nothing(app, client):
    client.post("/api/webhooks/n8n/candidate-event", json=_event(), headers={"X-N8N-Secret": "bad"})
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count(WorkflowRun.id))) == 0


def test_malformed_payload_is_rejected_without_recording(app, client):
    response = client.post(
        "/api/webhooks/n8n/candidate-event",
        content=b"{not json",
        headers={**WEBHOOK_HEADERS, "content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count(WorkflowRun.id))) == 0


@pytest.mark.parametrize(
    "override",
    [
        {"event_type": "candidate.deleted"},
        {"occurred_at": "2026-03-01T09:00:00"},
        {"event_id": "short"},
        {"event_id": "has spaces in it"},
        {"candidate_id": 0},
        {"payload": {f"k{i}": "v" for i in range(21)}},
        {"unexpected_field": "x"},
    ],
)
def test_schema_violations_are_rejected(client, override):
    response = client.post(
        "/api/webhooks/n8n/candidate-event", json=_event(**override), headers=WEBHOOK_HEADERS
    )
    assert response.status_code == 422


def test_oversized_webhook_body_is_rejected(client):
    big = _event(payload={"note": "x" * 500})
    body = {**big, "event_id": "evt-big-0001"}
    padded = {**body, "payload": {f"key{i:02d}": "y" * 500 for i in range(20)}}
    import json

    raw = json.dumps(padded) + " " * 17000
    response = client.post(
        "/api/webhooks/n8n/candidate-event",
        content=raw.encode(),
        headers={**WEBHOOK_HEADERS, "content-type": "application/json"},
    )
    assert response.status_code == 413


def test_valid_event_is_processed_once_and_duplicates_are_detected(client, app, seeded):
    cid, _jid = seeded
    first = client.post(
        "/api/webhooks/n8n/candidate-event", json=_event(candidate_id=cid), headers=WEBHOOK_HEADERS
    )
    assert first.status_code == 200
    assert first.json()["status"] == "completed"
    second = client.post(
        "/api/webhooks/n8n/candidate-event", json=_event(candidate_id=cid), headers=WEBHOOK_HEADERS
    )
    assert second.json()["status"] == "duplicate"
    assert second.json()["run_id"] == first.json()["run_id"]
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count(WorkflowRun.id))) == 1


def test_duplicate_does_not_reprocess_assessment(client, app, seeded):
    cid, jid = seeded
    event = _event(
        event_id="evt-assess-0001", event_type="assessment.requested", candidate_id=cid, job_id=jid
    )
    client.post("/api/webhooks/n8n/candidate-event", json=event, headers=WEBHOOK_HEADERS)
    client.post("/api/webhooks/n8n/candidate-event", json=event, headers=WEBHOOK_HEADERS)
    listed = client.get(f"/api/assessments?candidate_id={cid}").json()
    assert listed["total"] == 1


def test_assessment_request_creates_stored_assessment(client, seeded):
    cid, jid = seeded
    event = _event(
        event_id="evt-assess-0002", event_type="assessment.requested", candidate_id=cid, job_id=jid
    )
    response = client.post("/api/webhooks/n8n/candidate-event", json=event, headers=WEBHOOK_HEADERS)
    assert response.status_code == 200
    assert response.json()["outcome"] == "completed"
    run = client.get("/api/workflow-runs?outcome=completed").json()["items"][0]
    assert run["result"]["fitment_percent"] == 50.0
    assert client.get(f"/api/assessments/{run['result']['assessment_id']}").status_code == 200


def test_unknown_candidate_is_recorded_as_failed_and_returns_404(client):
    response = client.post(
        "/api/webhooks/n8n/candidate-event",
        json=_event(event_id="evt-missing-01", candidate_id=777),
        headers=WEBHOOK_HEADERS,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "candidate_not_found"
    failed = client.get("/api/workflow-runs?outcome=failed").json()
    assert failed["items"][0]["error_code"] == "candidate_not_found"


def test_assessment_without_resume_fails_safely(client, make_candidate, make_job):
    cid = make_candidate()["id"]
    jid = make_job()["id"]
    event = _event(event_id="evt-noresume-1", event_type="assessment.requested", candidate_id=cid, job_id=jid)
    response = client.post("/api/webhooks/n8n/candidate-event", json=event, headers=WEBHOOK_HEADERS)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "resume_not_available"


def test_overdue_feedback_drafts_message_awaiting_human_approval(client, seeded):
    cid, _jid = seeded
    event = _event(event_id="evt-overdue-01", event_type="feedback.overdue", candidate_id=cid)
    response = client.post("/api/webhooks/n8n/candidate-event", json=event, headers=WEBHOOK_HEADERS)
    assert response.json()["outcome"] == "awaiting_approval"
    run = client.get("/api/workflow-runs?outcome=awaiting_approval").json()["items"][0]
    assert run["approval_status"] == "awaiting_approval"
    assert "requires recruiter approval" in run["result"]["draft"]


def test_approval_records_decision_without_sending_anything(client, seeded, app):
    cid, _jid = seeded
    event = _event(event_id="evt-approve-01", event_type="feedback.overdue", candidate_id=cid)
    client.post("/api/webhooks/n8n/candidate-event", json=event, headers=WEBHOOK_HEADERS)
    run_id = client.get("/api/workflow-runs?outcome=awaiting_approval").json()["items"][0]["id"]
    decided = client.post(f"/api/workflow-runs/{run_id}/decision", json={"decision": "approve", "note": "ok"})
    assert decided.status_code == 200
    assert decided.json()["outcome"] == "approved_not_sent"
    again = client.post(f"/api/workflow-runs/{run_id}/decision", json={"decision": "reject"})
    assert again.status_code == 409
    with app.state.session_factory() as session:
        assert (
            session.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.action == "workflow.approved"))
            == 1
        )


def test_rejection_path_is_recorded(client, seeded):
    cid, _jid = seeded
    event = _event(event_id="evt-reject-01", event_type="feedback.overdue", candidate_id=cid)
    client.post("/api/webhooks/n8n/candidate-event", json=event, headers=WEBHOOK_HEADERS)
    run_id = client.get("/api/workflow-runs").json()["items"][-1]["id"]
    decided = client.post(f"/api/workflow-runs/{run_id}/decision", json={"decision": "reject"})
    assert decided.json()["outcome"] == "rejected"


def test_decision_on_missing_run_returns_404(client):
    assert client.post("/api/workflow-runs/999/decision", json={"decision": "approve"}).status_code == 404


def test_webhook_timestamps_are_utc_and_use_injected_clock(client, clock, seeded):
    cid, _jid = seeded
    clock.now = FIXED_NOW + timedelta(minutes=5)
    client.post(
        "/api/webhooks/n8n/candidate-event",
        json=_event(event_id="evt-clock-0001", candidate_id=cid),
        headers=WEBHOOK_HEADERS,
    )
    run = client.get("/api/workflow-runs").json()["items"][-1]
    assert run["created_at"] == "2026-03-01T09:05:00Z"


def test_concurrent_duplicate_insert_is_resolved_to_original_run(client, seeded, monkeypatch):
    """Simulates two requests racing: the pre-check misses, the INSERT hits the unique event_id."""
    from app.services import workflows

    cid, _jid = seeded
    event = _event(event_id="evt-race-0001", candidate_id=cid)
    original = client.post("/api/webhooks/n8n/candidate-event", json=event, headers=WEBHOOK_HEADERS).json()

    real_find = workflows._find_run
    calls = {"count": 0}

    def miss_first_lookup(session, event_id):
        calls["count"] += 1
        return None if calls["count"] == 1 else real_find(session, event_id)

    monkeypatch.setattr(workflows, "_find_run", miss_first_lookup)
    racing = client.post("/api/webhooks/n8n/candidate-event", json=event, headers=WEBHOOK_HEADERS)
    assert racing.status_code == 200
    assert racing.json()["status"] == "duplicate"
    assert racing.json()["run_id"] == original["run_id"]
