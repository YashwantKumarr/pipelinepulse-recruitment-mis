from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import NowDep, SessionDep
from app.errors import AppError
from app.models import Candidate, Interview, JobRequisition
from app.schemas import InterviewCreate, InterviewOut, InterviewUpdate, Page
from app.services.audit import record_audit
from app.timeutils import to_naive_utc

router = APIRouter(prefix="/api/interviews", tags=["interviews"])


def _validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AppError(
            422, "invalid_timezone", "timezone must be a valid IANA name, for example Asia/Kolkata."
        ) from exc
    return name


def _get_interview(session: SessionDep, interview_id: int) -> Interview:
    interview = session.get(Interview, interview_id)
    if interview is None:
        raise AppError(404, "not_found", "Interview not found.")
    return interview


@router.post("", status_code=201, response_model=InterviewOut)
def create_interview(payload: InterviewCreate, session: SessionDep, now: NowDep) -> InterviewOut:
    if session.get(Candidate, payload.candidate_id) is None:
        raise AppError(404, "not_found", "Candidate not found.")
    if payload.job_id is not None and session.get(JobRequisition, payload.job_id) is None:
        raise AppError(404, "not_found", "Job requisition not found.")
    timezone_name = _validate_timezone(payload.timezone)
    timestamp = to_naive_utc(now)
    interview = Interview(
        candidate_id=payload.candidate_id,
        job_id=payload.job_id,
        stage=payload.stage,
        scheduled_at=to_naive_utc(payload.scheduled_at),
        timezone=timezone_name,
        status="scheduled",
        notes=payload.notes,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(interview)
    session.flush()
    record_audit(
        session, entity_type="interview", entity_id=interview.id, action="interview.created", now=now
    )
    session.commit()
    return InterviewOut.model_validate(interview)


@router.get("", response_model=Page[InterviewOut])
def list_interviews(
    session: SessionDep,
    candidate_id: int | None = Query(None, ge=1),
    status: str | None = Query(None, max_length=20),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[InterviewOut]:
    stmt = select(Interview)
    if candidate_id is not None:
        stmt = stmt.where(Interview.candidate_id == candidate_id)
    if status:
        stmt = stmt.where(Interview.status == status)
    total = len(session.scalars(stmt).all())
    rows = session.scalars(
        stmt.order_by(Interview.scheduled_at, Interview.id).limit(limit).offset(offset)
    ).all()
    return Page[InterviewOut](
        items=[InterviewOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{interview_id}", response_model=InterviewOut)
def get_interview(interview_id: int, session: SessionDep) -> InterviewOut:
    return InterviewOut.model_validate(_get_interview(session, interview_id))


@router.patch("/{interview_id}", response_model=InterviewOut)
def update_interview(
    interview_id: int, payload: InterviewUpdate, session: SessionDep, now: NowDep
) -> InterviewOut:
    interview = _get_interview(session, interview_id)
    changes = payload.model_dump(exclude_none=True)

    if "status" in changes and changes["status"] != interview.status:
        if interview.status != "scheduled":
            raise AppError(
                409, "invalid_transition", f"An interview with status '{interview.status}' is final."
            )
        interview.status = changes["status"]
    if "scheduled_at" in changes:
        if interview.status != "scheduled":
            raise AppError(409, "reschedule_not_allowed", "Only scheduled interviews can be rescheduled.")
        interview.scheduled_at = to_naive_utc(changes["scheduled_at"])
    if "stage" in changes:
        interview.stage = changes["stage"]
    if "notes" in changes:
        interview.notes = changes["notes"]

    interview.updated_at = to_naive_utc(now)
    session.flush()
    record_audit(
        session,
        entity_type="interview",
        entity_id=interview.id,
        action="interview.updated",
        now=now,
        detail={"fields": sorted(changes)},
    )
    session.commit()
    return InterviewOut.model_validate(interview)
