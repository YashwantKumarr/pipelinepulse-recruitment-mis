"""Authenticated, idempotent automation events. Outbound communication is never sent here.

Outcomes:
- completed: processing finished (assessment stored, or event recorded).
- awaiting_approval: a draft was prepared and requires recruiter approval. Nothing is sent.
- failed: a referenced record was missing. The failure is recorded with an error code.
"""

from datetime import datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Candidate, JobRequisition, WorkflowRun
from app.schemas import WebhookEvent
from app.services.ai_provider import build_provider
from app.services.assessment import run_assessment
from app.services.audit import record_audit
from app.timeutils import to_naive_utc


def followup_draft(display_name: str) -> str:
    return (
        f"Hello {display_name},\n\nWe are following up on the status of your submission. "
        "Please reply if there is an update we should record.\n\n"
        "[DRAFT - requires recruiter approval before any message is sent]"
    )


def _find_run(session: Session, event_id: str) -> WorkflowRun | None:
    return session.scalar(select(WorkflowRun).where(WorkflowRun.event_id == event_id))


def _finish(session: Session, run: WorkflowRun, outcome: str, now: datetime, error: str | None = None):
    run.outcome = outcome
    run.error_code = error
    run.finished_at = to_naive_utc(now)
    session.flush()
    return run


def process_event(
    session: Session,
    *,
    event: WebhookEvent,
    raw_body: bytes,
    settings: Settings,
    now: datetime,
    transport=None,
) -> tuple[WorkflowRun, bool]:
    """Return (run, is_duplicate). Duplicate event_ids return the original run unchanged."""
    existing = _find_run(session, event.event_id)
    if existing is not None:
        return existing, True

    candidate = session.get(Candidate, event.candidate_id)
    run = WorkflowRun(
        event_id=event.event_id,
        event_type=event.event_type,
        candidate_id=candidate.id if candidate is not None else None,
        outcome="received",
        approval_status="not_required",
        payload_sha256=sha256(raw_body).hexdigest(),
        created_at=to_naive_utc(now),
    )
    session.add(run)
    try:
        session.flush()
    except IntegrityError:
        # A concurrent request inserted the same event_id first.
        session.rollback()
        original = _find_run(session, event.event_id)
        if original is None:
            raise
        return original, True

    if candidate is None:
        return _finish(session, run, "failed", now, "candidate_not_found"), False

    if event.event_type == "assessment.requested":
        job = session.get(JobRequisition, event.job_id) if event.job_id else None
        if job is None:
            return _finish(session, run, "failed", now, "job_not_found"), False
        if not candidate.resume_text:
            return _finish(session, run, "failed", now, "resume_not_available"), False
        assessment = run_assessment(
            session,
            candidate=candidate,
            job=job,
            now=now,
            provider=build_provider(settings, transport=transport),
        )
        run.result = {
            "assessment_id": assessment.id,
            "fitment_percent": assessment.fitment_percent,
            "ai_status": assessment.ai_status,
        }
        record_audit(
            session,
            entity_type="workflow_run",
            entity_id=run.event_id,
            action="workflow.assessment_completed",
            now=now,
            detail={"assessment_id": assessment.id},
        )
        return _finish(session, run, "completed", now), False

    if event.event_type == "feedback.overdue":
        run.result = {"draft": followup_draft(candidate.display_name), "requires_approval": True}
        run.approval_status = "awaiting_approval"
        return _finish(session, run, "awaiting_approval", now), False

    run.result = {"recorded": True}
    return _finish(session, run, "completed", now), False
