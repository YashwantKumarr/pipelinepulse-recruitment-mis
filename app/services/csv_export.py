"""CSV exports with stable headers, ordering, UTF-8 BOM, and formula-injection mitigation.

Excluded by design: candidate email addresses and resume text (unnecessary personal data).
"""

import csv
import io
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Candidate, Interview, PipelineEvent
from app.services.analytics import funnel_summary
from app.timeutils import iso_utc

DATASETS = ("candidates", "pipeline", "interviews", "funnel")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def render_csv(headers: list[str], rows: list[list]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([sanitize_cell(value) for value in row])
    return buffer.getvalue().encode("utf-8-sig")


def build_csv(session: Session, dataset: str, *, now: datetime, sla_hours: int) -> bytes:
    if dataset == "candidates":
        headers = ["candidate_id", "display_name", "source", "stage", "parse_status", "created_at"]
        candidates = session.scalars(select(Candidate).order_by(Candidate.id)).all()
        rows = [
            [c.id, c.display_name, c.source, c.stage, c.parse_status, iso_utc(c.created_at)]
            for c in candidates
        ]
    elif dataset == "pipeline":
        headers = ["event_id", "candidate_id", "prior_stage", "new_stage", "actor", "reason", "created_at"]
        events = session.scalars(
            select(PipelineEvent).order_by(PipelineEvent.created_at, PipelineEvent.id)
        ).all()
        rows = [
            [e.id, e.candidate_id, e.prior_stage, e.new_stage, e.actor, e.reason, iso_utc(e.created_at)]
            for e in events
        ]
    elif dataset == "interviews":
        headers = [
            "interview_id",
            "candidate_id",
            "job_id",
            "stage",
            "status",
            "scheduled_at_utc",
            "timezone",
        ]
        interviews = session.scalars(select(Interview).order_by(Interview.scheduled_at, Interview.id)).all()
        rows = [
            [i.id, i.candidate_id, i.job_id, i.stage, i.status, iso_utc(i.scheduled_at), i.timezone]
            for i in interviews
        ]
    elif dataset == "funnel":
        headers = ["stage", "count"]
        summary = funnel_summary(session, now=now, sla_hours=sla_hours)
        rows = [[s["stage"], s["count"]] for s in summary["stages"]]
    else:
        raise ValueError("unknown dataset")
    return render_csv(headers, rows)
