"""Recruiter-controlled pipeline rules. No AI or scoring path may call change_stage with a rejection."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import ALL_STAGES, PARSED_STATUSES, PIPELINE_ORDER, SIDE_STAGES, TERMINAL_STAGES
from app.errors import AppError
from app.models import Assessment, Candidate, PipelineEvent
from app.services.audit import record_audit
from app.timeutils import to_naive_utc


def allowed_transitions(current: str) -> frozenset[str]:
    if current in TERMINAL_STAGES:
        return frozenset()
    if current == "On Hold":
        return frozenset(PIPELINE_ORDER[1:-1]) | {"Rejected", "Withdrawn"}
    index = PIPELINE_ORDER.index(current)
    targets = set(SIDE_STAGES)
    if index > 0:
        targets.add(PIPELINE_ORDER[index - 1])  # correction back one step
    if index < len(PIPELINE_ORDER) - 1:
        targets.add(PIPELINE_ORDER[index + 1])
    return frozenset(targets)


def _has_assessment(session: Session, candidate_id: int) -> bool:
    found = session.scalar(select(Assessment.id).where(Assessment.candidate_id == candidate_id).limit(1))
    return found is not None


def change_stage(
    session: Session,
    candidate: Candidate,
    to_stage: str,
    *,
    actor: str | None,
    reason: str | None,
    now: datetime,
) -> PipelineEvent:
    if to_stage not in ALL_STAGES:
        raise AppError(422, "unknown_stage", "Unknown pipeline stage.")
    if to_stage == candidate.stage:
        raise AppError(409, "no_op_transition", "The candidate is already in that stage.")
    if to_stage not in allowed_transitions(candidate.stage):
        raise AppError(
            409, "invalid_transition", f"A candidate cannot move from '{candidate.stage}' to '{to_stage}'."
        )
    if to_stage == "Parsed" and candidate.parse_status not in PARSED_STATUSES:
        raise AppError(409, "precondition_failed", "A resume must be parsed before the Parsed stage.")
    if to_stage == "Assessed" and not _has_assessment(session, candidate.id):
        raise AppError(409, "precondition_failed", "An assessment is required before the Assessed stage.")

    timestamp = to_naive_utc(now)
    prior = candidate.stage
    event = PipelineEvent(
        candidate_id=candidate.id,
        prior_stage=prior,
        new_stage=to_stage,
        actor=actor,
        reason=reason,
        created_at=timestamp,
    )
    candidate.stage = to_stage
    candidate.updated_at = timestamp
    session.add(event)
    session.flush()
    record_audit(
        session,
        entity_type="candidate",
        entity_id=candidate.id,
        action="pipeline.stage_changed",
        now=now,
        detail={"from": prior, "to": to_stage},
    )
    return event
