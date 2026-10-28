from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.deps import NowDep, SessionDep
from app.errors import AppError
from app.models import JobRequisition
from app.schemas import JobCreate, JobOut, JobUpdate, Page
from app.services.audit import record_audit
from app.timeutils import to_naive_utc

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
NON_NULLABLE_FIELDS = {"title", "status", "requirements"}


def _get_job(session: SessionDep, job_id: int) -> JobRequisition:
    job = session.get(JobRequisition, job_id)
    if job is None:
        raise AppError(404, "not_found", "Job requisition not found.")
    return job


@router.get("", response_model=Page[JobOut])
def list_jobs(
    session: SessionDep,
    status: Literal["open", "archived"] | None = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[JobOut]:
    stmt = select(JobRequisition)
    count_stmt = select(func.count(JobRequisition.id))
    if status:
        stmt = stmt.where(JobRequisition.status == status)
        count_stmt = count_stmt.where(JobRequisition.status == status)
    total = session.scalar(count_stmt) or 0
    rows = session.scalars(stmt.order_by(JobRequisition.id).limit(limit).offset(offset)).all()
    return Page[JobOut](
        items=[JobOut.model_validate(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.post("", status_code=201, response_model=JobOut)
def create_job(payload: JobCreate, session: SessionDep, now: NowDep) -> JobOut:
    timestamp = to_naive_utc(now)
    job = JobRequisition(
        title=payload.title,
        description=payload.description,
        requirements=payload.requirements,
        location=payload.location,
        min_years=payload.min_years,
        max_years=payload.max_years,
        status="open",
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(job)
    session.flush()
    record_audit(session, entity_type="job", entity_id=job.id, action="job.created", now=now)
    session.commit()
    return JobOut.model_validate(job)


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, session: SessionDep) -> JobOut:
    return JobOut.model_validate(_get_job(session, job_id))


@router.patch("/{job_id}", response_model=JobOut)
def update_job(job_id: int, payload: JobUpdate, session: SessionDep, now: NowDep) -> JobOut:
    job = _get_job(session, job_id)
    changes = payload.model_dump(exclude_unset=True)
    for name, value in changes.items():
        if value is None and name in NON_NULLABLE_FIELDS:
            raise AppError(422, "validation_error", f"{name} cannot be null.")
    if not changes:
        return JobOut.model_validate(job)

    new_min = changes.get("min_years", job.min_years)
    new_max = changes.get("max_years", job.max_years)
    if new_min is not None and new_max is not None and new_max < new_min:
        raise AppError(422, "validation_error", "max_years must be greater than or equal to min_years.")

    for name, value in changes.items():
        setattr(job, name, value)
    job.updated_at = to_naive_utc(now)
    session.flush()
    action = "job.archived" if changes.get("status") == "archived" else "job.updated"
    record_audit(
        session,
        entity_type="job",
        entity_id=job.id,
        action=action,
        now=now,
        detail={"fields": sorted(changes)},
    )
    session.commit()
    return JobOut.model_validate(job)
