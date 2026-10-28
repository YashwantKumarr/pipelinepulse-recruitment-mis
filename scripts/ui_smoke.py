"""Optional browser smoke test (not run in CI).
Requires: pip install playwright && playwright install chromium

Usage (server already running with a fresh database):
    python scripts/ui_smoke.py http://127.0.0.1:8000
Exits non-zero on any failed step, console error, or Content-Security-Policy violation.
"""

import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
RESUME = ROOT / "sample_data" / "candidates" / "candidate_a.txt"


def main(base_url: str) -> int:
    problems: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        # The deliberate unsupported-file probe is expected to log one HTTP 415 in the browser console.
        expected_415 = "status of 415"

        def record_console(message):
            if message.type == "error" and expected_415 not in message.text:
                problems.append(f"console {message.type}: {message.text}")

        page.on("console", record_console)
        page.on("pageerror", lambda e: problems.append(f"page error: {e}"))

        page.goto(base_url)
        expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
        print("dashboard loaded")

        page.get_by_role("button", name="Jobs", exact=True).click()
        page.get_by_label("Title").fill("UI Smoke Role")
        page.get_by_label("Requirements (one per line)").fill("Python\nSQL\nAirflow")
        page.get_by_role("button", name="Create requisition").click()
        expect(page.get_by_role("cell", name="UI Smoke Role")).to_be_visible()
        print("job created via form")

        page.get_by_role("button", name="Candidates", exact=True).click()
        bad = ROOT / "scripts" / "_unsupported_probe.exe"
        bad.write_bytes(b"MZ-not-a-resume")
        page.locator("input[name=file]").set_input_files(str(bad))
        page.get_by_label("Display name").fill("Probe")
        page.get_by_role("button", name="Upload and parse").click()
        expect(page.get_by_role("alert")).to_contain_text("Supported formats")
        bad.unlink()
        print("unsupported file rejected with a visible, recoverable error")
        page.locator("input[name=file]").set_input_files(str(RESUME))
        page.get_by_label("Display name").fill("UI Smoke Candidate")
        page.get_by_role("button", name="Upload and parse").click()
        detail = page.locator("#candidate-detail")
        expect(detail).to_be_visible()
        expect(detail.get_by_role("heading", name="UI Smoke Candidate")).to_be_visible()
        expect(detail.get_by_text("Parsed", exact=True)).to_be_visible()
        print("resume uploaded and parsed")

        detail.get_by_label("Assess against job").select_option(label="UI Smoke Role")
        detail.get_by_role("button", name="Run fitment assessment").click()
        expect(page.get_by_text("Assessment result")).to_be_visible()
        expect(page.get_by_text("Fitment 66.7%")).to_be_visible()
        detail.screenshot(path=str(ROOT / "docs" / "screenshot-assessment.png"))
        print("assessment rendered: Fitment 66.7% (Python, SQL matched; Airflow missing)")

        detail.get_by_label("Move to stage").select_option("Assessment Pending")
        detail.get_by_role("button", name="Update stage").click()
        expect(detail.locator("dd", has_text="Assessment Pending")).to_be_visible()
        print("stage moved to Assessment Pending")

        page.get_by_role("button", name="Interviews", exact=True).click()
        expect(page.get_by_role("heading", name="Interviews", level=2)).to_be_visible()
        page.locator("#interview-form select[name=candidate_id]").select_option(index=1)
        page.locator("#interview-form input[name=scheduled_at]").fill("2026-11-02T10:30")
        page.get_by_role("button", name="Schedule").click()
        expect(page.get_by_text("Interview scheduled.")).to_be_visible()
        print("interview scheduled")

        page.get_by_role("button", name="Reports", exact=True).click()
        export = page.get_by_role("link", name="Download candidates CSV")
        expect(export).to_have_attribute("href", "/api/reports/export.csv?dataset=candidates")
        page.screenshot(path=str(ROOT / "docs" / "screenshot-reports.png"), full_page=True)
        print("reports view and export links verified")

        browser.close()

    if problems:
        print("PROBLEMS:")
        for item in problems:
            print("  -", item)
        return 1
    print("UI smoke test passed with no console errors")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"))
