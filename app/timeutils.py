"""UTC helpers. The database stores naive UTC datetimes; API output is UTC with a Z suffix."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required.")
    return value.astimezone(UTC).replace(tzinfo=None)


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = to_naive_utc(value)
    return value.replace(microsecond=0).isoformat() + "Z"
