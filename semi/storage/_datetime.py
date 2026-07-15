from datetime import datetime


def to_iso(dt: datetime) -> str:
    return dt.isoformat()


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)
