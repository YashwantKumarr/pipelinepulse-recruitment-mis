from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.sql import Select

from app.deps import NowDep, SessionDep, SettingsDep
from app.errors import AppError
from app.models import Candidate, PipelineEvent
from app.schemas import (
    CandidateCreate,
    CandidateDetail,
    CandidateSummary,
    CandidateUpdate,
    Page,
    PipelineEventOut,
    StageChange,
    normalize_email,
)
from app.services.audit import record_audit
from app.services.pipeline import change_stage
from app.services.resume_parser import normalize_text, parse_resume
from app.timeutils import to_naive_utc

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


def _get_candidate(session: SessionDep, candidate_id: int) -> Candidate:
    candidate = session.get(Candidate, candidate_id)
    if candidate is None:
        raise AppError(404, "not_found", "Candidate not found.")
    return candidate


def _store_upload(upload_dir: Path, storage_name: str, data: bytes) -> None:
    """storage_name is generated internally (uuid4). Client filenames never reach the filesystem."""
    upload_dir.mkdir(parents=True, exist_ok=True)
    with (upload_dir / storage_name).open("xb") as handle:
        handle.write(data)


def _apply_filters(stmt: Select, filters: list) -> Select:
    for condition in filters:
        stmt = stmt.where(condition)
    return stmt


@router.get("", response_model=Page[CandidateSummary])
def list_candidates(
    session: SessionDep,
    q: str | None = Query(None, max_length=100),
    stage: str | None = Query(None, max_length=40),
    source: str | None = Query(None, max_length=50),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[CandidateSummary]:
    filters = []
    if q and q.strip():
        filters.append(func.lower(Candidate.display_name).contains(q.strip().casefold(), autoescape=True))
    if stage:
        filters.append(Candidate.stage == stage)
    if source:
        filters.append(Candidate.source == source)
    total = session.scalar(_apply_filters(select(func.count(Candidate.id)), filters)) or 0
    rows = session.scalars(
        _apply_filters(select(Candidate), filters).order_by(Candidate.id).limit(limit).offset(offset)
    ).all()
    return Page[CandidateSummary](
        items=[CandidateSummary.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post("", status_code=201, response_model=CandidateSummary)
def create_candidate(payload: CandidateCreate, session: SessionDep, now: NowDep) -> CandidateSummary:
    timestamp = to_naive_utc(now)
    candidate = Candidate(
        display_name=payload.display_name,
        email=payload.email,
        source=payload.source,
        stage="New",
        parse_status="not_uploaded",
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(candidate)
    session.flush()
    record_audit(
        session,
        entity_type="candidate",
        entity_id=candidate.id,
        action="candidate.created",
        now=now,
        detail={"source": payload.source},
    )
    session.commit()
    return CandidateSummary.model_validate(candidate)


@router.post("/upload-resume", status_code=201, response_model=CandidateSummary)
async def upload_resume(
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
    file: UploadFile = File(...),
    display_name: str = Form(..., min_length=1, max_length=200),
    email: str | None = Form(None, max_length=254),
    source: str = Form("upload", min_length=1, max_length=50),
) -> CandidateSummary:
    name = display_name.strip()
    if not name:
        raise AppError(422, "validation_error", "display_name must not be blank.")
    try:
        clean_email = normalize_email(email)
    except ValueError as exc:
        raise AppError(422, "validation_error", "email must be a valid address.") from exc

    data = await file.read(settings.max_resume_bytes + 1)
    parsed = parse_resume(file.filename or "", data, settings.max_resume_bytes)
    storage_name = f"{uuid4().hex}.{parsed.file_format}"
    timestamp = to_naive_utc(now)
    candidate = Candidate(
        display_name=name,
        email=clean_email,
        source=source.strip() or "upload",
        stage="New",
        parse_status="parsed",
        resume_format=parsed.file_format,
        resume_storage_name=storage_name,
        resume_text=parsed.text,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(candidate)
    session.flush()
    _store_upload(settings.upload_dir, storage_name, data)
    change_stage(
        session, candidate, "Parsed", actor="system:resume-parser", reason="Resume text extracted", now=now
    )
    record_audit(
        session,
        entity_type="candidate",
        entity_id=candidate.id,
        action="candidate.resume_uploaded",
        now=now,
        detail={"format": parsed.file_format, "characters": len(parsed.text)},
    )
    session.commit()
    return CandidateSummary.model_validate(candidate)


@router.get("/{candidate_id}", response_model=CandidateDetail)
def get_candidate(candidate_id: int, session: SessionDep) -> CandidateDetail:
    return CandidateDetail.model_validate(_get_candidate(session, candidate_id))


@router.patch("/{candidate_id}", response_model=CandidateDetail)
def update_candidate(
    candidate_id: int, payload: CandidateUpdate, session: SessionDep, now: NowDep
) -> CandidateDetail:
    candidate = _get_candidate(session, candidate_id)
    changes = payload.model_dump(exclude_unset=True)
    for name in ("display_name", "source", "resume_text"):
        if name in changes and changes[name] is None:
            raise AppError(422, "validation_error", f"{name} cannot be null.")
    if "resume_text" in changes:
        corrected = normalize_text(changes["resume_text"])
        if not corrected:
            raise AppError(422, "validation_error", "resume_text must contain text.")
        changes["resume_text"] = corrected
        candidate.parse_status = "manually_corrected"
    for name, value in changes.items():
        setattr(candidate, name, value)
    candidate.updated_at = to_naive_utc(now)
    session.flush()
    record_audit(
        session,
        entity_type="candidate",
        entity_id=candidate.id,
        action="candidate.updated",
        now=now,
        detail={"fields": sorted(changes)},
    )
    session.commit()
    return CandidateDetail.model_validate(candidate)


@router.patch("/{candidate_id}/stage", response_model=CandidateSummary)
def update_stage(
    candidate_id: int, payload: StageChange, session: SessionDep, now: NowDep
) -> CandidateSummary:
    candidate = _get_candidate(session, candidate_id)
    change_stage(
        session,
        candidate,
        payload.to_stage,
        actor=payload.actor or "recruiter",
        reason=payload.reason,
        now=now,
    )
    session.commit()
    return CandidateSummary.model_validate(candidate)


@router.get("/{candidate_id}/pipeline-events", response_model=list[PipelineEventOut])
def list_pipeline_events(candidate_id: int, session: SessionDep) -> list[PipelineEventOut]:
    _get_candidate(session, candidate_id)
    events = session.scalars(
        select(PipelineEvent)
        .where(PipelineEvent.candidate_id == candidate_id)
        .order_by(PipelineEvent.created_at, PipelineEvent.id)
    ).all()
    return [PipelineEventOut.model_validate(e) for e in events]
