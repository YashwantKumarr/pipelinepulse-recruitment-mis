from app.main import create_app
from app.seed import SEED_NOW, seed_demo
from app.config import Settings
from fastapi.testclient import TestClient


def _fresh_app(tmp_path, name, clock):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}", upload_dir=tmp_path / f"{name}-uploads"
    )
    return create_app(settings=settings, clock=lambda: SEED_NOW)


def _snapshot(client):
    assessments = client.get("/api/assessments?limit=100").json()["items"]
    return [
        (a["candidate_id"], a["job_id"], a["fitment_percent"], a["summary"], a["criteria"])
        for a in sorted(assessments, key=lambda a: (a["candidate_id"], a["job_id"]))
    ]


def test_seed_loads_demo_records(tmp_path):
    app = _fresh_app(tmp_path, "seed.db", None)
    result = seed_demo(app.state.session_factory, max_bytes=5 * 1024 * 1024)
    assert result == {"skipped": False, "jobs": 2, "candidates": 3, "assessments": 6}
    with TestClient(app) as client:
        funnel = client.get("/api/reports/funnel").json()
        assert funnel["total_candidates"] == 3


def test_seed_is_idempotent(tmp_path):
    app = _fresh_app(tmp_path, "idem.db", None)
    seed_demo(app.state.session_factory, max_bytes=5 * 1024 * 1024)
    second = seed_demo(app.state.session_factory, max_bytes=5 * 1024 * 1024)
    assert second["skipped"] is True
    with TestClient(app) as client:
        assert client.get("/api/jobs").json()["total"] == 2


def test_two_clean_seeds_produce_identical_business_results(tmp_path):
    """Acceptance criterion from the engineering prompt: equivalent clean states, equivalent results."""
    first_app = _fresh_app(tmp_path, "run1.db", None)
    second_app = _fresh_app(tmp_path, "run2.db", None)
    seed_demo(first_app.state.session_factory, max_bytes=5 * 1024 * 1024)
    seed_demo(second_app.state.session_factory, max_bytes=5 * 1024 * 1024)
    with TestClient(first_app) as first, TestClient(second_app) as second:
        assert _snapshot(first) == _snapshot(second)
        assert (
            first.get("/api/reports/funnel").json()["stages"]
            == second.get("/api/reports/funnel").json()["stages"]
        )
        assert (
            first.get("/api/reports/export.csv?dataset=funnel").content
            == second.get("/api/reports/export.csv?dataset=funnel").content
        )


def test_seed_expected_fitment_values_are_stable(tmp_path):
    app = _fresh_app(tmp_path, "expected.db", None)
    seed_demo(app.state.session_factory, max_bytes=5 * 1024 * 1024)
    with TestClient(app) as client:
        percents = {
            (a["candidate_id"], a["job_id"]): a["fitment_percent"]
            for a in client.get("/api/assessments?limit=100").json()["items"]
        }
    assert percents[(1, 1)] == 83.3  # Candidate A vs Data Engineer: 5 of 6
    assert percents[(2, 2)] == 100.0  # Candidate B vs Frontend: 6 of 6
    assert percents[(3, 2)] == 16.7  # Candidate C vs Frontend: JavaScript only
    assert percents[(3, 1)] == 0.0  # Candidate C: Airflow is needs_review, not matched
