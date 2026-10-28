from sqlalchemy import select

from app.constants import ALL_STAGES
from app.models import AuditEvent, PipelineEvent
from app.services.pipeline import allowed_transitions


def test_forward_back_and_side_transitions_are_allowed():
    assert "Parsed" in allowed_transitions("New")
    assert "On Hold" in allowed_transitions("New")
    assert "New" not in allowed_transitions("New")  # no backwards past the start
    assert "Assessed" in allowed_transitions("Assessment Pending")
    assert "Assessment Pending" in allowed_transitions("Assessed")  # correction step back


def test_terminal_stages_have_no_exits():
    for stage in ("Joined", "Rejected", "Withdrawn"):
        assert allowed_transitions(stage) == frozenset()


def test_on_hold_cannot_return_to_new():
    assert "New" not in allowed_transitions("On Hold")
    assert "Shortlisted" in allowed_transitions("On Hold")


def test_every_stage_is_known():
    assert set(ALL_STAGES) >= {"New", "Joined", "On Hold", "Rejected"}


def test_manual_candidate_cannot_jump_to_parsed(client, make_candidate):
    candidate = make_candidate()
    response = client.patch(f"/api/candidates/{candidate['id']}/stage", json={"to_stage": "Parsed"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "precondition_failed"


def test_skipping_stages_is_rejected(client, upload):
    candidate = upload("cv.txt", b"Python", name="Skipper").json()
    response = client.patch(f"/api/candidates/{candidate['id']}/stage", json={"to_stage": "Shortlisted"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_transition"


def test_same_stage_is_a_no_op_error(client, upload):
    candidate = upload("cv.txt", b"Python", name="Same").json()
    response = client.patch(f"/api/candidates/{candidate['id']}/stage", json={"to_stage": "Parsed"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_op_transition"


def test_unknown_stage_is_rejected_by_schema(client, upload):
    candidate = upload("cv.txt", b"Python", name="Unknown").json()
    response = client.patch(f"/api/candidates/{candidate['id']}/stage", json={"to_stage": "Hired-ish"})
    assert response.status_code == 422


def test_assessed_requires_an_assessment(client, upload, make_job):
    candidate = upload("cv.txt", b"Python", name="Needs Assessment").json()
    client.patch(f"/api/candidates/{candidate['id']}/stage", json={"to_stage": "Assessment Pending"})
    response = client.patch(f"/api/candidates/{candidate['id']}/stage", json={"to_stage": "Assessed"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "precondition_failed"

    job = make_job(requirements=["Python"])
    client.post("/api/assessments", json={"candidate_id": candidate["id"], "job_id": job["id"]})
    response = client.patch(f"/api/candidates/{candidate['id']}/stage", json={"to_stage": "Assessed"})
    assert response.status_code == 200
    assert response.json()["stage"] == "Assessed"


def test_full_happy_path_records_history_with_actor_and_reason(client, upload, app):
    candidate = upload("cv.txt", b"Python", name="Walker").json()
    cid = candidate["id"]
    steps = ["Assessment Pending", "Assessed", "Shortlisted"]
    job = client.post("/api/jobs", json={"title": "R", "requirements": ["Python"]}).json()
    client.post("/api/assessments", json={"candidate_id": cid, "job_id": job["id"]})
    for index, stage in enumerate(steps):
        response = client.patch(
            f"/api/candidates/{cid}/stage",
            json={"to_stage": stage, "actor": "recruiter-a", "reason": f"step {index}"},
        )
        assert response.status_code == 200, response.text

    history = client.get(f"/api/candidates/{cid}/pipeline-events").json()
    assert [e["new_stage"] for e in history] == ["Parsed", "Assessment Pending", "Assessed", "Shortlisted"]
    assert history[0]["actor"] == "system:resume-parser"
    assert history[1]["prior_stage"] == "Parsed"
    assert history[2]["reason"] == "step 1"
    assert history[-1]["actor"] == "recruiter-a"

    with app.state.session_factory() as session:
        audit = session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "pipeline.stage_changed", AuditEvent.entity_id == str(cid)
            )
        ).all()
        assert len(audit) == 4
        assert session.scalar(select(PipelineEvent).where(PipelineEvent.candidate_id == cid)) is not None


def test_rejection_is_terminal(client, upload):
    candidate = upload("cv.txt", b"Python", name="Terminal").json()
    cid = candidate["id"]
    assert (
        client.patch(
            f"/api/candidates/{cid}/stage", json={"to_stage": "Rejected", "reason": "Test"}
        ).status_code
        == 200
    )
    response = client.patch(f"/api/candidates/{cid}/stage", json={"to_stage": "Parsed"})
    assert response.status_code == 409


def test_on_hold_can_be_resumed_into_active_pipeline(client, upload):
    candidate = upload("cv.txt", b"Python", name="Paused").json()
    cid = candidate["id"]
    assert client.patch(f"/api/candidates/{cid}/stage", json={"to_stage": "On Hold"}).status_code == 200
    response = client.patch(f"/api/candidates/{cid}/stage", json={"to_stage": "Assessment Pending"})
    assert response.status_code == 200


def test_active_candidate_can_be_withdrawn(client, upload):
    candidate = upload("cv.txt", b"Python", name="Withdrawn Person").json()
    cid = candidate["id"]
    response = client.patch(
        f"/api/candidates/{cid}/stage", json={"to_stage": "Withdrawn", "reason": "Declined"}
    )
    assert response.status_code == 200
    assert client.patch(f"/api/candidates/{cid}/stage", json={"to_stage": "On Hold"}).status_code == 409
