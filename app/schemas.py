import re
from datetime import datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from app.constants import (
    ALL_STAGES,
    INTERVIEW_STAGES,
    INTERVIEW_STATUSES,
    JOB_STATUSES,
    PAYMENT_STATUSES,
    REVIEW_STATUSES,
    WEBHOOK_EVENT_TYPES,
)
from app.timeutils import iso_utc

T = TypeVar("T")

UtcOut = Annotated[datetime, PlainSerializer(lambda v: iso_utc(v), return_type=str, when_used="json")]

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def normalize_email(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if len(cleaned) > 254 or not EMAIL_RE.match(cleaned):
        raise ValueError("email must be a valid address.")
    return cleaned


def _require_aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("Timestamp must include a UTC offset, for example 2026-03-01T10:00:00+05:30.")
    return value


def _clean_requirements(items: list[str]) -> list[str]:
    cleaned = [item.strip() for item in items]
    if any(not 1 <= len(item) <= 200 for item in cleaned):
        raise ValueError("Each requirement must be 1-200 characters.")
    return cleaned


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---- Jobs -----------------------------------------------------------------


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    requirements: list[str] = Field(min_length=1, max_length=50)
    location: str = Field(default="", max_length=120)
    min_years: int | None = Field(default=None, ge=0, le=60)
    max_years: int | None = Field(default=None, ge=0, le=60)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank.")
        return value.strip()

    @field_validator("requirements")
    @classmethod
    def _requirements(cls, value: list[str]) -> list[str]:
        return _clean_requirements(value)

    @model_validator(mode="after")
    def _years(self) -> "JobCreate":
        if self.min_years is not None and self.max_years is not None and self.max_years < self.min_years:
            raise ValueError("max_years must be greater than or equal to min_years.")
        return self


class JobUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    requirements: list[str] | None = Field(default=None, min_length=1, max_length=50)
    location: str | None = Field(default=None, max_length=120)
    min_years: int | None = Field(default=None, ge=0, le=60)
    max_years: int | None = Field(default=None, ge=0, le=60)
    status: str | None = None

    @field_validator("requirements")
    @classmethod
    def _requirements(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_requirements(value)

    @field_validator("status")
    @classmethod
    def _status(cls, value: str | None) -> str | None:
        if value is not None and value not in JOB_STATUSES:
            raise ValueError("status must be open or archived.")
        return value


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str
    requirements: list[str]
    location: str
    min_years: int | None
    max_years: int | None
    status: str
    created_at: UtcOut
    updated_at: UtcOut


# ---- Candidates -----------------------------------------------------------


class CandidateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    source: str = Field(default="manual", min_length=1, max_length=50)

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name must not be blank.")
        return value.strip()

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return normalize_email(value)


class CandidateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    source: str | None = Field(default=None, min_length=1, max_length=50)
    resume_text: str | None = Field(default=None, max_length=200_000)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return normalize_email(value)


class CandidateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    display_name: str
    email: str | None
    source: str
    stage: str
    parse_status: str
    resume_format: str | None
    created_at: UtcOut
    updated_at: UtcOut


class CandidateDetail(CandidateSummary):
    resume_text: str | None


class StageChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_stage: str = Field(min_length=1, max_length=40)
    actor: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("to_stage")
    @classmethod
    def _stage(cls, value: str) -> str:
        if value not in ALL_STAGES:
            raise ValueError("to_stage is not a recognised pipeline stage.")
        return value


class PipelineEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    candidate_id: int
    prior_stage: str | None
    new_stage: str
    actor: str | None
    reason: str | None
    created_at: UtcOut


# ---- Assessments ----------------------------------------------------------


class AssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: int = Field(ge=1)
    job_id: int = Field(ge=1)


class AssessmentReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_status: str
    review_note: str | None = Field(default=None, max_length=500)

    @field_validator("review_status")
    @classmethod
    def _status(cls, value: str) -> str:
        if value not in REVIEW_STATUSES:
            raise ValueError("review_status must be pending_review, accepted or overridden.")
        return value


class CriterionOut(BaseModel):
    criterion: str
    status: str
    evidence: str | None = None
    note: str | None = None


class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    candidate_id: int
    job_id: int
    assessment_version: str
    provider: str
    model: str | None
    ai_status: str
    summary_source: str
    summary: str
    fitment_percent: float | None
    criteria: list[CriterionOut]
    ai_disagreements: list[dict[str, Any]]
    review_status: str
    review_note: str | None
    created_at: UtcOut
    reviewed_at: UtcOut | None
    decision_support_only: bool = True


# ---- Interviews -----------------------------------------------------------


class InterviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: int = Field(ge=1)
    job_id: int | None = Field(default=None, ge=1)
    stage: str
    scheduled_at: datetime
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("stage")
    @classmethod
    def _stage(cls, value: str) -> str:
        if value not in INTERVIEW_STAGES:
            raise ValueError("stage must be one of: " + ", ".join(INTERVIEW_STAGES))
        return value

    @field_validator("scheduled_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _require_aware(value)


class InterviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None = None
    scheduled_at: datetime | None = None
    stage: str | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("status")
    @classmethod
    def _status(cls, value: str | None) -> str | None:
        if value is not None and value not in INTERVIEW_STATUSES:
            raise ValueError("status must be one of: " + ", ".join(INTERVIEW_STATUSES))
        return value

    @field_validator("stage")
    @classmethod
    def _stage(cls, value: str | None) -> str | None:
        if value is not None and value not in INTERVIEW_STAGES:
            raise ValueError("stage must be one of: " + ", ".join(INTERVIEW_STAGES))
        return value

    @field_validator("scheduled_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value)


class InterviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    candidate_id: int
    job_id: int | None
    stage: str
    scheduled_at: UtcOut
    timezone: str
    status: str
    notes: str | None
    created_at: UtcOut
    updated_at: UtcOut


# ---- Finance (demonstration only) -----------------------------------------


class FeeDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: int = Field(ge=1)
    job_id: int = Field(ge=1)
    currency: str = Field(default="INR", pattern=r"^(INR|USD)$")
    annual_ctc: str = Field(min_length=1, max_length=20)
    fee_percent: str = Field(min_length=1, max_length=8)


class FeeDraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    candidate_id: int
    job_id: int
    currency: str
    annual_ctc: str
    fee_percent: str
    draft_amount: str
    status: str
    label: str
    created_at: UtcOut


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: int = Field(ge=1)
    amount: str = Field(min_length=1, max_length=20)
    status: str = "pending"
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        if value not in PAYMENT_STATUSES:
            raise ValueError("status must be one of: " + ", ".join(PAYMENT_STATUSES))
        return value


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    draft_id: int
    amount: str
    status: str
    notes: str | None
    is_demo: bool
    label: str
    created_at: UtcOut


# ---- Webhooks and workflow runs -------------------------------------------


class WebhookEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    event_type: str
    candidate_id: int = Field(ge=1)
    job_id: int | None = Field(default=None, ge=1)
    occurred_at: datetime
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("event_type")
    @classmethod
    def _type(cls, value: str) -> str:
        if value not in WEBHOOK_EVENT_TYPES:
            raise ValueError("event_type is not supported.")
        return value

    @field_validator("occurred_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @field_validator("payload")
    @classmethod
    def _payload(cls, value: dict) -> dict:
        if len(value) > 20:
            raise ValueError("payload may contain at most 20 keys.")
        for key, item in value.items():
            if len(key) > 60 or (isinstance(item, str) and len(item) > 500):
                raise ValueError("payload keys must be 60 characters or fewer; values 500 or fewer.")
        return value


class WorkflowRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_id: str
    event_type: str
    candidate_id: int | None
    outcome: str
    approval_status: str
    error_code: str | None
    result: dict | None
    created_at: UtcOut
    finished_at: UtcOut | None


class WorkflowDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    note: str | None = Field(default=None, max_length=500)

    @field_validator("decision")
    @classmethod
    def _decision(cls, value: str) -> str:
        if value not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject.")
        return value
