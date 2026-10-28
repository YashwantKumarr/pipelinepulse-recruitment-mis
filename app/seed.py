"""Load synthetic demo data. Idempotent: does nothing if any job already exists.

Run:  python -m app.seed
All timestamps come from SEED_NOW so two fresh seeds produce identical business results.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.config import load_settings
from app.database import init_db, make_engine, make_session_factory
from app.models import Candidate, JobRequisition
from app.services.assessment import run_assessment
from app.services.pipeline import change_stage
from app.services.resume_parser import parse_resume
from app.timeutils import to_naive_utc

SEED_NOW = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


def seed_demo(
    session_factory, *, max_bytes: int, sample_dir: Path = SAMPLE_DIR, now: datetime = SEED_NOW
) -> dict:
    with session_factory() as session:
        if session.scalar(select(func.count(JobRequisition.id))):
            return {"skipped": True, "jobs": 0, "candidates": 0, "assessments": 0}

        timestamp = to_naive_utc(now)
        jobs = json.loads((sample_dir / "jobs.json").read_text(encoding="utf-8"))
        job_rows = []
        for item in jobs:
            job = JobRequisition(
                title=item["title"],
                description=item.get("description", ""),
                requirements=item["requirements"],
                location=item.get("location", ""),
                status="open",
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(job)
            job_rows.append(job)
        session.flush()

        manifest = json.loads((sample_dir / "candidates.json").read_text(encoding="utf-8"))
        candidate_rows = []
        for item in manifest:
            data = (sample_dir / "candidates" / item["file"]).read_bytes()
            parsed = parse_resume(item["file"], data, max_bytes)
            candidate = Candidate(
                display_name=item["display_name"],
                email=item.get("email"),
                source=item["source"],
                stage="New",
                parse_status="parsed",
                resume_format=parsed.file_format,
                resume_text=parsed.text,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(candidate)
            session.flush()
            change_stage(
                session, candidate, "Parsed", actor="seed", reason="Synthetic resume loaded", now=now
            )
            candidate_rows.append(candidate)

        assessment_count = 0
        for candidate in candidate_rows:
            for job in job_rows:
                run_assessment(session, candidate=candidate, job=job, now=now, provider=None)
                assessment_count += 1
        session.commit()
        return {
            "skipped": False,
            "jobs": len(job_rows),
            "candidates": len(candidate_rows),
            "assessments": assessment_count,
        }


if __name__ == "__main__":
    settings = load_settings()
    engine = make_engine(settings.database_url)
    init_db(engine)
    print(seed_demo(make_session_factory(engine), max_bytes=settings.max_resume_bytes))
