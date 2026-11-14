"""All times are IST, stored as ISO-8601 strings with a +05:30 offset (lexicographically sortable)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def now() -> datetime:
    """Real wall-clock now in IST. PAKKA_FAKE_NOW pins it (used by the seeded demo and tests)."""
    fake = os.getenv("PAKKA_FAKE_NOW")
    if fake:
        return parse(fake)
    return datetime.now(IST).replace(microsecond=0)


def now_iso() -> str:
    return iso(now())


def parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST).replace(microsecond=0).isoformat()


def normalize_ts(ts: str) -> str:
    """Any ISO input -> canonical IST string so string comparisons are valid."""
    return iso(parse(ts))


def days_between(a: str, b: str) -> float:
    return (parse(b) - parse(a)).total_seconds() / 86400.0
