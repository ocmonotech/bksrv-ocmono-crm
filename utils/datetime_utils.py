"""Application clock in Asia/Kolkata (IST) using zoneinfo."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def ist_now() -> datetime:
    return datetime.now(IST)


def as_ist(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize to IST-aware datetime (MySQL may return naive values)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def ist_now_iso() -> str:
    return ist_now().isoformat()


def ist_today():
    """Calendar date in IST (for Date columns / business 'today')."""
    return ist_now().date()
