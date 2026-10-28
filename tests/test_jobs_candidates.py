from sqlalchemy import select

from app.models import AuditEvent


def test_job_create_and_get(client, make_job):
    job = make_job(title="Backend Engineer", requirements=["Python", "FastAPI"])
    fetched = client.get(f"/api/jobs/{job['id']}").json()
    assert fetched["title"] == "Backend Engineer"
    assert fetched["requirements"] == ["Python", "FastAPI"]
    assert fetched["status"] == "open"
    assert fetched["created_at"].endswith("Z")


def test_job_requirements_are_trimmed_and_blank_rejected(client):
    ok = client.post("/api/jobs", json={"title": "T", "requirements": ["  Python  "]}).json()
    assert ok["requirements"] == ["Python"]
    response = client.post("/api/jobs", json={"title": "T", "requirements": ["   "]})
    assert response.status_code == 422


def test_job_requires_at_least_one_requirement(client):
    response = client.post("/api/jobs", json={"title": "T", "requirements": []})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_job_year_range_must_be_ordered(client):
    response = client.post(
        "/api/jobs", json={"title": "T", "requirements": ["Go"], "min_years": 5, "max_years": 2}
    )
    assert response.status_code == 422


def test_job_list_pagination_and_status_filter(client, make_job):
    for index in range(3):
        make_job(title=f"Role {index}")
    archived = make_job(title="Old role")
    client.patch(f"/api/jobs/{archived['id']}", json={"status": "archived"})

    page = client.get("/api/jobs?limit=2&offset=0").json()
    assert page["total"] == 4
    assert len(page["items"]) == 2
    assert page["limit"] == 2

    only_archived = client.get("/api/jobs?status=archived").json()
    assert only_archived["total"] == 1
    assert only_archived["items"][0]["title"] == "Old role"


def test_job_update_and_archive_are_audited(app, client, make_job):
    job = make_job()
    response = client.patch(f"/api/jobs/{job['id']}", json={"status": "archived"})
    assert response.json()["status"] == "archived"
    with app.state.session_factory() as session:
        actions = session.scalars(
            select(AuditEvent.action).where(
                AuditEvent.entity_type == "job", AuditEvent.entity_id == str(job["id"])
            )
        ).all()
    assert "job.created" in actions
    assert "job.archived" in actions


def test_job_patch_rejects_null_title_and_invalid_status(client, make_job):
    job = make_job()
    assert client.patch(f"/api/jobs/{job['id']}", json={"title": None}).status_code == 422
    assert client.patch(f"/api/jobs/{job['id']}", json={"status": "deleted"}).status_code == 422


def test_job_patch_checks_combined_year_range(client):
    job = client.post("/api/jobs", json={"title": "T", "requirements": ["Go"], "min_years": 3}).json()
    response = client.patch(f"/api/jobs/{job['id']}", json={"max_years": 1})
    assert response.status_code == 422


def test_missing_job_returns_error_envelope(client):
    response = client.get("/api/jobs/9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_candidate_manual_create_and_detail(client, make_candidate):
    candidate = make_candidate(display_name="  Priya Sample  ", email="sample@example.com")
    assert candidate["display_name"] == "Priya Sample"
    detail = client.get(f"/api/candidates/{candidate['id']}").json()
    assert detail["stage"] == "New"
    assert detail["parse_status"] == "not_uploaded"
    assert detail["resume_text"] is None


def test_candidate_email_validation(client):
    response = client.post("/api/candidates", json={"display_name": "A", "email": "not-an-email"})
    assert response.status_code == 422
    assert "not-an-email" not in response.text


def test_candidate_search_is_case_insensitive_and_escapes_wildcards(client, make_candidate):
    make_candidate(display_name="Alice Example")
    make_candidate(display_name="Bob Sample")
    assert client.get("/api/candidates?q=ALICE").json()["total"] == 1
    assert client.get("/api/candidates?q=%25").json()["total"] == 0
    assert client.get("/api/candidates?q=_").json()["total"] == 0


def test_candidate_filters_by_stage_and_source(client, make_candidate):
    make_candidate(display_name="One", source="referral")
    make_candidate(display_name="Two", source="job_board")
    assert client.get("/api/candidates?source=job_board").json()["total"] == 1
    assert client.get("/api/candidates?stage=New").json()["total"] == 2


def test_candidate_patch_corrects_resume_text(client, make_candidate):
    candidate = make_candidate()
    response = client.patch(
        f"/api/candidates/{candidate['id']}",
        json={"resume_text": "Corrected\r\n\r\n\r\n\r\ntext  "},
    )
    body = response.json()
    assert body["parse_status"] == "manually_corrected"
    assert body["resume_text"] == "Corrected\n\ntext"


def test_candidate_patch_rejects_null_and_blank_resume(client, make_candidate):
    candidate = make_candidate()
    assert client.patch(f"/api/candidates/{candidate['id']}", json={"resume_text": None}).status_code == 422
    assert client.patch(f"/api/candidates/{candidate['id']}", json={"resume_text": "   "}).status_code == 422


def test_candidate_patch_can_clear_email(client, make_candidate):
    candidate = make_candidate(email="clear.me@example.com")
    response = client.patch(f"/api/candidates/{candidate['id']}", json={"email": None})
    assert response.json()["email"] is None


def test_missing_candidate_returns_404(client):
    assert client.get("/api/candidates/424242").status_code == 404
    assert client.patch("/api/candidates/424242/stage", json={"to_stage": "Parsed"}).status_code == 404
