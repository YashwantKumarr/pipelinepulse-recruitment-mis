from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.timeutils import to_naive_utc


def record_audit(
    session: Session,
    *,
    entity_type: str,
    entity_id: object,
    action: str,
    now: datetime,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append an audit row. Details must contain identifiers and field names only, never content."""
    session.add(
        AuditEvent(
            entity_type=entity_type,
            entity_id=str(entity_id),
            action=action,
            detail=detail or {},
            created_at=to_naive_utc(now),
        )
    )
