import csv
import io
from datetime import timedelta

from tests.conftest import FIXED_NOW


def _move_to_submitted(client, upload, make_job, name):
    candidate = upload("cv.txt", b"Python developer", name=name, source="referral").json()
    job = make_job(requirements=["Python"])
    cid = candidate["id"]
    client.post("/api/assessments", json={"candidate_id": cid, "job_id": job["id"]})
    for stage in ("Assessment Pending", "Assessed", "Shortlisted", "Submitted to Client"):
        response = client.patch(f"/api/candidates/{cid}/stage", json={"to_stage": stage, "actor": "test"})
        assert response.status_code == 200, response.text
    return cid


def _csv_rows(response_content: bytes):
    text = response_content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def test_funnel_on_empty_dataset_is_all_zero(client):
    body = client.get("/api/reports/funnel").json()
    assert body["total_candidates"] == 0
    assert body["jobs"]["total"] == 0
    assert all(stage["count"] == 0 for stage in body["stages"])
    assert body["overdue_feedback"]["items"] == []
    assert body["interviews"]["by_status"] == {"scheduled": 0, "completed": 0, "cancelled": 0, "no_show": 0}


def test_funnel_counts_stages_sources_and_jobs(client, upload, make_job):
    upload("a.txt", b"Python", name="A", source="referral")
    upload("b.txt", b"SQL", name="B", source="job_board")
    make_job()
    body = client.get("/api/reports/funnel").json()
    counts = {s["stage"]: s["count"] for s in body["stages"]}
    assert counts["Parsed"] == 2
    assert body["total_candidates"] == 2
    assert body["sources"] == [{"source": "job_board", "count": 1}, {"source": "referral", "count": 1}]
    assert body["jobs"]["open"] == 1


def test_overdue_feedback_threshold_is_strict_and_uses_injected_clock(client, upload, make_job, clock):
    cid = _move_to_submitted(client, upload, make_job, "Waiting Candidate")

    clock.now = FIXED_NOW + timedelta(hours=72)
    at_threshold = client.get("/api/reports/funnel").json()["overdue_feedback"]
    assert at_threshold["items"] == []

    clock.now = FIXED_NOW + timedelta(hours=72, seconds=1)
    just_over = client.get("/api/reports/funnel").json()["overdue_feedback"]
    assert [item["candidate_id"] for item in just_over["items"]] == [cid]

    clock.now = FIXED_NOW + timedelta(hours=72, minutes=1)
    overdue = client.get("/api/reports/funnel").json()["overdue_feedback"]
    assert overdue["items"][0]["hours_waiting"] == 72.02


def test_interviews_awaiting_outcome_are_counted_using_clock(client, upload, clock):
    cid = upload("cv.txt", b"Python", name="Interview Person").json()["id"]
    client.post(
        "/api/interviews",
        json={
            "candidate_id": cid,
            "stage": "HR",
            "scheduled_at": "2026-03-01T12:00:00+00:00",
            "timezone": "UTC",
        },
    )
    clock.now = FIXED_NOW + timedelta(hours=10)
    body = client.get("/api/reports/funnel").json()
    assert body["interviews"]["awaiting_outcome"] == 1
    assert body["interviews"]["upcoming"] == 0


def test_candidates_csv_has_stable_headers_bom_and_excludes_personal_data(client, make_candidate):
    make_candidate(display_name="Exported Person", email="private@example.com")
    response = client.get("/api/reports/export.csv?dataset=candidates")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content.startswith(b"\xef\xbb\xbf")
    rows = _csv_rows(response.content)
    assert rows[0] == ["candidate_id", "display_name", "source", "stage", "parse_status", "created_at"]
    assert "private@example.com" not in response.text
    assert rows[1][1] == "Exported Person"


def test_exports_are_byte_identical_across_repeated_calls(client, upload):
    upload("a.txt", b"Python", name="Repeat A")
    upload("b.txt", b"SQL", name="Repeat B")
    first = client.get("/api/reports/export.csv?dataset=candidates").content
    second = client.get("/api/reports/export.csv?dataset=candidates").content
    assert first == second


def test_formula_injection_is_neutralised_in_csv(client, make_candidate):
    make_candidate(display_name='=HYPERLINK("http://example.invalid")', source="+cmd")
    rows = _csv_rows(client.get("/api/reports/export.csv?dataset=candidates").content)
    assert rows[1][1].startswith("'=HYPERLINK")
    assert rows[1][2] == "'+cmd"


def test_pipeline_export_contains_history_and_neutralises_reason(client, upload):
    cid = upload("cv.txt", b"Python", name="History Person").json()["id"]
    client.patch(f"/api/candidates/{cid}/stage", json={"to_stage": "On Hold", "reason": "=2+2"})
    rows = _csv_rows(client.get("/api/reports/export.csv?dataset=pipeline").content)
    assert rows[0][:4] == ["event_id", "candidate_id", "prior_stage", "new_stage"]
    assert rows[-1][5] == "'=2+2"


def test_interview_and_funnel_exports_have_headers(client, upload):
    rows = _csv_rows(client.get("/api/reports/export.csv?dataset=interviews").content)
    assert rows == [
        ["interview_id", "candidate_id", "job_id", "stage", "status", "scheduled_at_utc", "timezone"]
    ]
    funnel_rows = _csv_rows(client.get("/api/reports/export.csv?dataset=funnel").content)
    assert funnel_rows[0] == ["stage", "count"]
    assert len(funnel_rows) == 13  # header + 9 pipeline stages + 3 side stages
