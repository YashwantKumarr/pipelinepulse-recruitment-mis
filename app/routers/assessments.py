from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import NowDep, SessionDep, SettingsDep, TransportDep
from app.errors import AppError
from app.models import Assessment, Candidate, JobRequisition
from app.schemas import AssessmentCreate, AssessmentOut, AssessmentReview, Page
from app.services.ai_provider import build_provider
from app.services.assessment import run_assessment
from app.services.audit import record_audit
from app.timeutils import to_naive_utc

router = APIRouter(prefix="/api/assessments", tags=["assessments"])


def _get_assessment(session: SessionDep, assessment_id: int) -> Assessment:
    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise AppError(404, "not_found", "Assessment not found.")
    return assessment


@router.post("", status_code=201, response_model=AssessmentOut)
def create_assessment(
    payload: AssessmentCreate,
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
    transport: TransportDep,
) -> AssessmentOut:
    candidate = session.get(Candidate, payload.candidate_id)
    if candidate is None:
        raise AppError(404, "not_found", "Candidate not found.")
    job = session.get(JobRequisition, payload.job_id)
    if job is None:
        raise AppError(404, "not_found", "Job requisition not found.")
    if job.status == "archived":
        raise AppError(409, "job_archived", "Archived jobs cannot be assessed.")
    if not candidate.resume_text:
        raise AppError(409, "resume_not_available", "The candidate has no resume text to assess.")

    assessment = run_assessment(
        session,
        candidate=candidate,
        job=job,
        now=now,
        provider=build_provider(settings, transport=transport),
    )
    session.commit()
    return AssessmentOut.model_validate(assessment)


@router.get("", response_model=Page[AssessmentOut])
def list_assessments(
    session: SessionDep,
    candidate_id: int | None = Query(None, ge=1),
    job_id: int | None = Query(None, ge=1),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[AssessmentOut]:
    stmt = select(Assessment)
    if candidate_id is not None:
        stmt = stmt.where(Assessment.candidate_id == candidate_id)
    if job_id is not None:
        stmt = stmt.where(Assessment.job_id == job_id)
    rows = session.scalars(stmt.order_by(Assessment.id).limit(limit).offset(offset)).all()
    total = len(session.scalars(stmt).all())
    return Page[AssessmentOut](
        items=[AssessmentOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{assessment_id}", response_model=AssessmentOut)
def get_assessment(assessment_id: int, session: SessionDep) -> AssessmentOut:
    return AssessmentOut.model_validate(_get_assessment(session, assessment_id))


@router.patch("/{assessment_id}/review", response_model=AssessmentOut)
def review_assessment(
    assessment_id: int, payload: AssessmentReview, session: SessionDep, now: NowDep
) -> AssessmentOut:
    assessment = _get_assessment(session, assessment_id)
    assessment.review_status = payload.review_status
    assessment.review_note = payload.review_note
    assessment.reviewed_at = to_naive_utc(now)
    session.flush()
    record_audit(
        session,
        entity_type="assessment",
        entity_id=assessment.id,
        action="assessment.reviewed",
        now=now,
        detail={"review_status": payload.review_status},
    )
    session.commit()
    return AssessmentOut.model_validate(assessment)
