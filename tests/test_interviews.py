def _candidate(upload):
    return upload("cv.txt", b"Python", name="Interviewee").json()


def _schedule(client, candidate_id, **overrides):
    body = {
        "candidate_id": candidate_id,
        "stage": "Technical",
        "scheduled_at": "2026-03-02T10:00:00+05:30",
        "timezone": "Asia/Kolkata",
        "notes": "Panel interview",
    }
    body.update(overrides)
    return client.post("/api/interviews", json=body)


def test_offset_timestamp_is_stored_and_returned_as_utc(client, upload):
    cid = _candidate(upload)["id"]
    response = _schedule(client, cid)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["scheduled_at"] == "2026-03-02T04:30:00Z"
    assert body["timezone"] == "Asia/Kolkata"
    assert body["status"] == "scheduled"


def test_naive_timestamp_without_offset_is_rejected(client, upload):
    cid = _candidate(upload)["id"]
    response = _schedule(client, cid, scheduled_at="2026-03-02T10:00:00")
    assert response.status_code == 422


def test_invalid_timezone_is_rejected(client, upload):
    cid = _candidate(upload)["id"]
    response = _schedule(client, cid, timezone="Mars/Olympus")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_timezone"


def test_path_like_timezone_is_rejected(client, upload):
    cid = _candidate(upload)["id"]
    assert _schedule(client, cid, timezone="../../etc/passwd").status_code == 422


def test_unknown_stage_and_missing_candidate(client, upload):
    cid = _candidate(upload)["id"]
    assert _schedule(client, cid, stage="Lunch").status_code == 422
    assert _schedule(client, 99999).status_code == 404


def test_interview_status_moves_once_from_scheduled(client, upload):
    cid = _candidate(upload)["id"]
    interview = _schedule(client, cid).json()
    done = client.patch(f"/api/interviews/{interview['id']}", json={"status": "completed"})
    assert done.json()["status"] == "completed"
    back = client.patch(f"/api/interviews/{interview['id']}", json={"status": "scheduled"})
    assert back.status_code == 409
    assert back.json()["error"]["code"] == "invalid_transition"


def test_invalid_status_value_is_rejected(client, upload):
    cid = _candidate(upload)["id"]
    interview = _schedule(client, cid).json()
    response = client.patch(f"/api/interviews/{interview['id']}", json={"status": "maybe"})
    assert response.status_code == 422


def test_reschedule_only_while_scheduled(client, upload):
    cid = _candidate(upload)["id"]
    interview = _schedule(client, cid).json()
    moved = client.patch(
        f"/api/interviews/{interview['id']}", json={"scheduled_at": "2026-03-03T12:00:00+00:00"}
    )
    assert moved.json()["scheduled_at"] == "2026-03-03T12:00:00Z"

    client.patch(f"/api/interviews/{interview['id']}", json={"status": "cancelled"})
    blocked = client.patch(
        f"/api/interviews/{interview['id']}", json={"scheduled_at": "2026-03-04T12:00:00+00:00"}
    )
    assert blocked.status_code == 409


def test_status_and_reschedule_in_one_request_is_checked_together(client, upload):
    cid = _candidate(upload)["id"]
    interview = _schedule(client, cid).json()
    response = client.patch(
        f"/api/interviews/{interview['id']}",
        json={"status": "completed", "scheduled_at": "2026-03-04T12:00:00+00:00"},
    )
    assert response.status_code == 409


def test_interview_list_filters_by_candidate_and_status(client, upload):
    cid = _candidate(upload)["id"]
    first = _schedule(client, cid).json()
    _schedule(client, cid, stage="HR")
    client.patch(f"/api/interviews/{first['id']}", json={"status": "no_show"})
    assert client.get(f"/api/interviews?candidate_id={cid}").json()["total"] == 2
    assert client.get("/api/interviews?status=no_show").json()["total"] == 1


def test_missing_interview_returns_404(client):
    assert client.get("/api/interviews/424242").status_code == 404
    assert client.patch("/api/interviews/424242", json={"status": "completed"}).status_code == 404
