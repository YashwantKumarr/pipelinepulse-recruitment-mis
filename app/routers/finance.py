from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import select

from app.constants import PAYMENT_STATUSES
from app.deps import NowDep, SessionDep
from app.errors import AppError
from app.models import Candidate, JobRequisition, PaymentRecord, PlacementFeeDraft
from app.schemas import FeeDraftCreate, FeeDraftOut, PaymentCreate, PaymentOut
from app.services.audit import record_audit
from app.services.finance import (
    DEMO_LABEL,
    compute_draft_amount,
    format_money,
    parse_money,
    parse_percent,
)
from app.timeutils import to_naive_utc

router = APIRouter(prefix="/api/finance", tags=["finance (demonstration)"])
_COUNTED_PAYMENT_STATUSES = frozenset({"pending", "recorded"})


@router.post("/placement-fee-drafts", status_code=201, response_model=FeeDraftOut)
def create_fee_draft(payload: FeeDraftCreate, session: SessionDep, now: NowDep) -> FeeDraftOut:
    if session.get(Candidate, payload.candidate_id) is None:
        raise AppError(404, "not_found", "Candidate not found.")
    if session.get(JobRequisition, payload.job_id) is None:
        raise AppError(404, "not_found", "Job requisition not found.")
    ctc = parse_money(payload.annual_ctc, "annual_ctc")
    percent = parse_percent(payload.fee_percent)
    draft = PlacementFeeDraft(
        candidate_id=payload.candidate_id,
        job_id=payload.job_id,
        currency=payload.currency,
        annual_ctc=format_money(ctc),
        fee_percent=f"{percent.normalize():f}",
        draft_amount=format_money(compute_draft_amount(ctc, percent)),
        status="draft",
        label=DEMO_LABEL,
        created_at=to_naive_utc(now),
    )
    session.add(draft)
    session.flush()
    record_audit(
        session,
        entity_type="placement_fee_draft",
        entity_id=draft.id,
        action="finance.draft_created",
        now=now,
    )
    session.commit()
    return FeeDraftOut.model_validate(draft)


@router.get("/placement-fee-drafts", response_model=list[FeeDraftOut])
def list_fee_drafts(session: SessionDep) -> list[FeeDraftOut]:
    rows = session.scalars(select(PlacementFeeDraft).order_by(PlacementFeeDraft.id)).all()
    return [FeeDraftOut.model_validate(r) for r in rows]


@router.post("/payments", status_code=201, response_model=PaymentOut)
def create_payment(payload: PaymentCreate, session: SessionDep, now: NowDep) -> PaymentOut:
    draft = session.get(PlacementFeeDraft, payload.draft_id)
    if draft is None:
        raise AppError(404, "not_found", "Placement-fee draft not found.")
    amount = parse_money(payload.amount, "amount")
    existing = session.scalars(select(PaymentRecord).where(PaymentRecord.draft_id == draft.id)).all()
    already = sum(
        (Decimal(p.amount) for p in existing if p.status in _COUNTED_PAYMENT_STATUSES), Decimal("0")
    )
    if payload.status in _COUNTED_PAYMENT_STATUSES and already + amount > Decimal(draft.draft_amount):
        raise AppError(422, "payment_exceeds_draft", "Demonstration payments cannot exceed the draft amount.")
    if payload.status not in PAYMENT_STATUSES:
        raise AppError(422, "validation_error", "Unknown payment status.")
    record = PaymentRecord(
        draft_id=draft.id,
        amount=format_money(amount),
        status=payload.status,
        notes=payload.notes,
        is_demo=True,
        label=DEMO_LABEL,
        created_at=to_naive_utc(now),
    )
    session.add(record)
    session.flush()
    record_audit(
        session, entity_type="payment_record", entity_id=record.id, action="finance.payment_recorded", now=now
    )
    session.commit()
    return PaymentOut.model_validate(record)


@router.get("/payments", response_model=list[PaymentOut])
def list_payments(session: SessionDep) -> list[PaymentOut]:
    rows = session.scalars(select(PaymentRecord).order_by(PaymentRecord.id)).all()
    return [PaymentOut.model_validate(r) for r in rows]
