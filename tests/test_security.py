from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def test_frontend_has_no_inline_scripts_or_event_attributes():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html
    assert " onclick=" not in html and " onsubmit=" not in html


def test_frontend_never_uses_html_injection_sinks():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    for dangerous in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert dangerous not in script, dangerous


def test_validation_errors_do_not_echo_submitted_values(client):
    secret = "SUPER-SECRET-CANDIDATE-VALUE"
    response = client.post("/api/candidates", json={"display_name": secret, "email": secret + "@@"})
    assert response.status_code == 422
    assert secret not in response.text


def test_server_errors_do_not_leak_details(app, client, monkeypatch):
    from app.routers import jobs

    def explode(*_args, **_kwargs):
        raise RuntimeError("internal detail that must stay private")

    monkeypatch.setattr(jobs, "_get_job", explode)
    from fastapi.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as safe_client:
        response = safe_client.get("/api/jobs/1")
    assert response.status_code == 500
    assert "internal detail" not in response.text
    assert response.json()["error"]["code"] == "internal_error"


def test_upload_size_limit_is_enforced_in_bytes_not_trusting_client(settings, client, upload):
    response = upload("notes.md", b"x" * (settings.max_resume_bytes + 1), name="Oversize")
    assert response.status_code == 413


def test_no_authentication_is_claimed_in_api_description(client):
    description = client.get("/openapi.json").json()["info"]["description"]
    assert "No authentication is implemented" in description


def test_no_docker_artifacts_in_repository():
    root = Path(__file__).resolve().parent.parent
    names = {p.name.lower() for p in root.rglob("*") if p.is_file()}
    assert "dockerfile" not in names
    assert "docker-compose.yml" not in names
    assert ".dockerignore" not in names
