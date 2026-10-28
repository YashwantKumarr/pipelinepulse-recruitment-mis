import hmac

from fastapi import APIRouter, Query, Request
from pydantic import ValidationError
from sqlalchemy import select

from app.deps import NowDep, SessionDep, SettingsDep, TransportDep
from app.errors import AppError
from app.models import WorkflowRun
from app.schemas import Page, WebhookEvent, WorkflowDecision, WorkflowRunOut
from app.services.audit import record_audit
from app.services.workflows import process_event
from app.timeutils import to_naive_utc

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
runs_router = APIRouter(prefix="/api/workflow-runs", tags=["workflow runs"])
MAX_WEBHOOK_BYTES = 16_384
_FAILURE_STATUS = {
    "candidate_not_found": 404,
    "job_not_found": 404,
    "resume_not_available": 409,
}


@router.post("/n8n/candidate-event")
async def n8n_candidate_event(
    request: Request, session: SessionDep, settings: SettingsDep, now: NowDep, transport: TransportDep
) -> dict:
    if not settings.enable_n8n_webhooks:
        raise AppError(404, "not_found", "Not found.")

    provided = request.headers.get("x-n8n-secret", "").encode()
    expected = settings.n8n_shared_secret.encode()
    if not expected or not hmac.compare_digest(provided, expected):
        raise AppError(401, "unauthorized", "Invalid webhook credentials.")

    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise AppError(413, "payload_too_large", "Webhook payload exceeds 16 KB.")
    try:
        event = WebhookEvent.model_validate_json(raw)
    except ValidationError as exc:
        raise AppError(422, "validation_error", "Malformed webhook payload.") from exc

    run, duplicate = process_event(
        session, event=event, raw_body=raw, settings=settings, now=now, transport=transport
    )
    if duplicate:
        session.commit()
        return {"status": "duplicate", "run_id": run.id, "outcome": run.outcome}

    session.commit()
    if run.outcome == "failed":
        status = _FAILURE_STATUS.get(run.error_code or "", 422)
        raise AppError(status, run.error_code or "failed", "Workflow could not be completed.")
    return {"status": run.outcome, "run_id": run.id, "outcome": run.outcome}


@runs_router.get("", response_model=Page[WorkflowRunOut])
def list_runs(
    session: SessionDep,
    outcome: str | None = Query(None, max_length=30),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[WorkflowRunOut]:
    stmt = select(WorkflowRun)
    if outcome:
        stmt = stmt.where(WorkflowRun.outcome == outcome)
    total = len(session.scalars(stmt).all())
    rows = session.scalars(stmt.order_by(WorkflowRun.id).limit(limit).offset(offset)).all()
    return Page[WorkflowRunOut](
        items=[WorkflowRunOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@runs_router.post("/{run_id}/decision", response_model=WorkflowRunOut)
def decide(run_id: int, payload: WorkflowDecision, session: SessionDep, now: NowDep) -> WorkflowRunOut:
    run = session.get(WorkflowRun, run_id)
    if run is None:
        raise AppError(404, "not_found", "Workflow run not found.")
    if run.approval_status != "awaiting_approval":
        raise AppError(409, "not_awaiting_approval", "This workflow run is not awaiting approval.")
    if payload.decision == "approve":
        run.approval_status = "approved"
        run.outcome = "approved_not_sent"  # approval is recorded; no external message is sent
    else:
        run.approval_status = "rejected"
        run.outcome = "rejected"
    run.finished_at = to_naive_utc(now)
    session.flush()
    record_audit(
        session,
        entity_type="workflow_run",
        entity_id=run.event_id,
        action=f"workflow.{payload.decision}d",
        now=now,
        detail={"run_id": run.id},
    )
    session.commit()
    return WorkflowRunOut.model_validate(run)
