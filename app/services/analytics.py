"""Deterministic funnel, source, job, interview and overdue-feedback metrics."""

from datetime import datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.constants import ALL_STAGES, INTERVIEW_STATUSES, SUBMITTED_STAGE
from app.models import Assessment, Candidate, Interview, JobRequisition, PipelineEvent
from app.timeutils import iso_utc, to_naive_utc


def _overdue_feedback(session: Session, now_naive: datetime, sla_hours: int) -> dict:
    """Candidates whose current stage is Submitted to Client for MORE than sla_hours (strict)."""
    candidates = session.scalars(
        select(Candidate).where(Candidate.stage == SUBMITTED_STAGE).order_by(Candidate.id)
    ).all()
    items = []
    for candidate in candidates:
        entered_at = (
            session.scalar(
                select(PipelineEvent.created_at)
                .where(PipelineEvent.candidate_id == candidate.id, PipelineEvent.new_stage == SUBMITTED_STAGE)
                .order_by(PipelineEvent.created_at.desc(), PipelineEvent.id.desc())
                .limit(1)
            )
            or candidate.updated_at
        )
        hours_waiting = (now_naive - entered_at).total_seconds() / 3600
        if hours_waiting > sla_hours:
            items.append(
                {
                    "candidate_id": candidate.id,
                    "display_name": candidate.display_name,
                    "entered_stage_at": iso_utc(entered_at),
                    "hours_waiting": round(hours_waiting, 2),
                }
            )
    return {"threshold_hours": sla_hours, "items": items}


def funnel_summary(session: Session, *, now: datetime, sla_hours: int) -> dict:
    now_naive = to_naive_utc(now)

    stage_counts = dict(
        session.execute(select(Candidate.stage, func.count()).group_by(Candidate.stage)).all()
    )
    stages = [{"stage": s, "count": int(stage_counts.get(s, 0))} for s in ALL_STAGES]

    source_rows = session.execute(select(Candidate.source, func.count()).group_by(Candidate.source)).all()
    sources = [
        {"source": name, "count": int(count)}
        for name, count in sorted(source_rows, key=lambda row: (-row[1], row[0]))
    ]

    job_counts = dict(
        session.execute(select(JobRequisition.status, func.count()).group_by(JobRequisition.status)).all()
    )
    jobs_with_assessments = session.scalar(select(func.count(distinct(Assessment.job_id)))) or 0

    interview_counts = dict(
        session.execute(select(Interview.status, func.count()).group_by(Interview.status)).all()
    )
    upcoming = (
        session.scalar(
            select(func.count(Interview.id)).where(
                Interview.status == "scheduled", Interview.scheduled_at >= now_naive
            )
        )
        or 0
    )
    awaiting_outcome = (
        session.scalar(
            select(func.count(Interview.id)).where(
                Interview.status == "scheduled", Interview.scheduled_at < now_naive
            )
        )
        or 0
    )

    return {
        "generated_at": iso_utc(now_naive),
        "total_candidates": sum(int(v) for v in stage_counts.values()),
        "stages": stages,
        "sources": sources,
        "jobs": {
            "open": int(job_counts.get("open", 0)),
            "archived": int(job_counts.get("archived", 0)),
            "total": sum(int(v) for v in job_counts.values()),
            "with_assessments": int(jobs_with_assessments),
        },
        "assessments": {
            "total": int(session.scalar(select(func.count(Assessment.id))) or 0),
        },
        "interviews": {
            "by_status": {s: int(interview_counts.get(s, 0)) for s in INTERVIEW_STATUSES},
            "upcoming": int(upcoming),
            "awaiting_outcome": int(awaiting_outcome),
        },
        "overdue_feedback": _overdue_feedback(session, now_naive, sla_hours),
    }
