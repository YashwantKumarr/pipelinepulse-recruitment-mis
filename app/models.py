from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class JobRequisition(Base):
    __tablename__ = "job_requisitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    requirements: Mapped[list] = mapped_column(JSON, default=lambda: [])
    location: Mapped[str] = mapped_column(String(120), default="")
    min_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="manual", index=True)
    stage: Mapped[str] = mapped_column(String(40), default="New", index=True)
    parse_status: Mapped[str] = mapped_column(String(30), default="not_uploaded")
    resume_format: Mapped[str | None] = mapped_column(String(10), nullable=True)
    resume_storage_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (Index("ix_assessments_candidate_job", "candidate_id", "job_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_requisitions.id"), index=True)
    assessment_version: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ai_status: Mapped[str] = mapped_column(String(80))
    summary_source: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(Text)
    fitment_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    criteria: Mapped[list] = mapped_column(JSON, default=lambda: [])
    ai_disagreements: Mapped[list] = mapped_column(JSON, default=lambda: [])
    review_status: Mapped[str] = mapped_column(String(30), default="pending_review")
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"
    __table_args__ = (Index("ix_pipeline_candidate_created", "candidate_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    prior_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_stage: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Interview(Base):
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("job_requisitions.id"), nullable=True)
    stage: Mapped[str] = mapped_column(String(40))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    timezone: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class PlacementFeeDraft(Base):
    """DEMONSTRATION ONLY. Amounts are stored as decimal strings to avoid float rounding."""

    __tablename__ = "placement_fee_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_requisitions.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    annual_ctc: Mapped[str] = mapped_column(String(40))
    fee_percent: Mapped[str] = mapped_column(String(10))
    draft_amount: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    label: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class PaymentRecord(Base):
    """DEMONSTRATION ONLY. No payment is processed or transferred."""

    __tablename__ = "payment_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("placement_fee_drafts.id"), index=True)
    amount: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    label: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True)
    event_type: Mapped[str] = mapped_column(String(60))
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30))
    approval_status: Mapped[str] = mapped_column(String(30), default="not_required")
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(DateTime)
