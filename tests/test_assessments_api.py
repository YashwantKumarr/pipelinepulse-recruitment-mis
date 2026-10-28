from sqlalchemy import select

from app.models import Assessment, AuditEvent


def _upload_text(upload, text, name="Sample Candidate"):
    response = upload("cv.txt", text.encode("utf-8"), name=name)
    assert response.status_code == 201, response.text
    return response.json()


def test_assessment_returns_criteria_and_decision_support_label(client, upload, make_job):
    candidate = _upload_text(upload, "Python and SQL in production.")
    job = make_job(requirements=["Python", "SQL", "Airflow"])
    response = client.post("/api/assessments", json={"candidate_id": candidate["id"], "job_id": job["id"]})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["decision_support_only"] is True
    assert body["review_status"] == "pending_review"
    assert body["fitment_percent"] == 66.7
    statuses = {c["criterion"]: c["status"] for c in body["criteria"]}
    assert statuses == {"Python": "matched", "SQL": "matched", "Airflow": "missing"}
    assert body["ai_status"] == "disabled"
    assert body["summary_source"] == "rules"


def test_assessment_never_changes_pipeline_stage(client, upload, make_job):
    candidate = _upload_text(upload, "Nothing relevant here.")
    job = make_job(requirements=["Kubernetes"])
    client.post("/api/assessments", json={"candidate_id": candidate["id"], "job_id": job["id"]})
    detail = client.get(f"/api/candidates/{candidate['id']}").json()
    assert detail["stage"] == "Parsed"


def test_assessment_requires_resume_text(client, make_candidate, make_job):
    candidate = make_candidate()
    job = make_job()
    response = client.post("/api/assessments", json={"candidate_id": candidate["id"], "job_id": job["id"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "resume_not_available"


def test_archived_job_cannot_be_assessed(client, upload, make_job):
    candidate = _upload_text(upload, "Python.")
    job = make_job()
    client.patch(f"/api/jobs/{job['id']}", json={"status": "archived"})
    response = client.post("/api/assessments", json={"candidate_id": candidate["id"], "job_id": job["id"]})
    assert response.status_code == 409


def test_assessment_with_unknown_references_returns_404(client, upload, make_job):
    candidate = _upload_text(upload, "Python.")
    job = make_job()
    assert client.post("/api/assessments", json={"candidate_id": 999, "job_id": job["id"]}).status_code == 404
    assert (
        client.post("/api/assessments", json={"candidate_id": candidate["id"], "job_id": 999}).status_code
        == 404
    )


def test_assessment_list_filters_and_get(client, upload, make_job):
    candidate = _upload_text(upload, "Python and SQL.")
    job_a = make_job(requirements=["Python"])
    job_b = make_job(requirements=["SQL"])
    for job in (job_a, job_b):
        client.post("/api/assessments", json={"candidate_id": candidate["id"], "job_id": job["id"]})
    listed = client.get(f"/api/assessments?candidate_id={candidate['id']}&job_id={job_a['id']}").json()
    assert listed["total"] == 1
    assert client.get(f"/api/assessments/{listed['items'][0]['id']}").status_code == 200
    assert client.get("/api/assessments/999999").status_code == 404


def test_review_records_recruiter_decision_and_validates_status(client, upload, make_job):
    candidate = _upload_text(upload, "Python.")
    job = make_job(requirements=["Python"])
    assessment = client.post(
        "/api/assessments", json={"candidate_id": candidate["id"], "job_id": job["id"]}
    ).json()
    response = client.patch(
        f"/api/assessments/{assessment['id']}/review",
        json={"review_status": "overridden", "review_note": "Recruiter verified the evidence."},
    )
    assert response.json()["review_status"] == "overridden"
    assert response.json()["reviewed_at"].endswith("Z")
    assert (
        client.patch(
            f"/api/assessments/{assessment['id']}/review", json={"review_status": "auto_rejected"}
        ).status_code
        == 422
    )


def test_assessment_is_audited_without_resume_content(app, client, upload, make_job):
    candidate = _upload_text(upload, "CONFIDENTIAL-RESUME-BODY Python.")
    job = make_job(requirements=["Python"])
    client.post("/api/assessments", json={"candidate_id": candidate["id"], "job_id": job["id"]})
    with app.state.session_factory() as session:
        rows = session.scalars(select(AuditEvent).where(AuditEvent.action == "assessment.created")).all()
        assert rows
        assert all("CONFIDENTIAL" not in str(row.detail) for row in rows)
        assert session.scalar(select(Assessment.id)) is not None
