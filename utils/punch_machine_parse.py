"""Parse punch machine export rows into username + datetime (IST wall time, naive)."""

from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, date, time
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as date_parser

from utils.datetime_utils import IST

# Normalized header -> canonical role
USERNAME_HEADER_ALIASES = (
    "username",
    "user_name",
    "userid",
    "user_id",
    "empcode",
    "emp_code",
    "employeeid",
    "employee_id",
    "employee_code",
    "emp_id",
    "id",
    "cardno",
    "card_no",
    "enrollid",
    "enroll_id",
    "code",
)

# Do not include bare "time" here — use date+time pair when columns are split.
DATETIME_HEADER_ALIASES = (
    "datetime",
    "date_time",
    "punchtime",
    "punch_time",
    "clocktime",
    "clock_time",
    "logtime",
    "log_time",
    "recordtime",
    "record_time",
    "logdatetime",
    "log_datetime",
)

DATE_HEADER_ALIASES = ("date", "punchdate", "punch_date", "logdate", "log_date", "attdate", "att_date")
TIME_HEADER_ALIASES = ("time", "punchtime", "punch_time", "clocktime", "intime", "outtime")


def normalize_key(k: str) -> str:
    if not k:
        return ""
    s = str(k).strip().lower()
    s = re.sub(r"[\s\-/]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s


def normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        nk = normalize_key(str(k))
        if nk:
            out[nk] = v
    return out


def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def parse_punch_datetime_ist(val: Any) -> Optional[datetime]:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        dt = val
    elif isinstance(val, date) and not isinstance(val, datetime):
        return datetime.combine(val, time(0, 0))
    else:
        s = _cell_str(val)
        if not s:
            return None
        try:
            dt = date_parser.parse(s, dayfirst=True)
        except (ValueError, TypeError, OverflowError):
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(IST).replace(tzinfo=None)
    return dt


def _find_username_key(norm: Dict[str, Any]) -> Optional[str]:
    for alias in USERNAME_HEADER_ALIASES:
        if alias in norm and _cell_str(norm[alias]):
            return alias
    for key in norm:
        if key in USERNAME_HEADER_ALIASES and _cell_str(norm[key]):
            return key
    return None


def _find_datetime_key(norm: Dict[str, Any]) -> Optional[str]:
    for alias in DATETIME_HEADER_ALIASES:
        if alias in norm:
            return alias
    return None


def _find_date_time_pair(norm: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    dk, tk = None, None
    for a in DATE_HEADER_ALIASES:
        if a in norm and _cell_str(norm[a]):
            dk = a
            break
    for a in TIME_HEADER_ALIASES:
        if a in norm and _cell_str(norm[a]) and a != dk:
            tk = a
            break
    return dk, tk


def extract_username_and_punch(norm: Dict[str, Any]) -> Tuple[Optional[str], Optional[datetime]]:
    """Return (raw_identifier, punch_at naive IST) from one normalized row dict."""
    uk = _find_username_key(norm)
    raw_user = _cell_str(norm[uk]) if uk else ""

    dt_key = _find_datetime_key(norm)
    punch_at: Optional[datetime] = None
    if dt_key:
        punch_at = parse_punch_datetime_ist(norm[dt_key])
    else:
        dk, tk = _find_date_time_pair(norm)
        if dk and tk:
            dpart = parse_punch_datetime_ist(norm[dk])
            tpart = parse_punch_datetime_ist(norm[tk])
            if dpart and tpart:
                punch_at = datetime.combine(
                    dpart.date(),
                    tpart.time(),
                )
            elif dpart:
                punch_at = dpart
        elif dk:
            punch_at = parse_punch_datetime_ist(norm[dk])

    if not raw_user or not punch_at:
        return None, None
    return raw_user, punch_at


def resolve_username_with_note(
    raw: str, users: List[Any], note_json: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """Try raw key, then optional machine export `name` inside JSON `note_json`."""
    u, err = resolve_username(raw, users)
    if u or not note_json:
        return u, err
    try:
        meta = json.loads(note_json)
        nm = meta.get("name")
        if nm and str(nm).strip():
            return resolve_username(str(nm).strip(), users)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return u, err


def resolve_username(raw: str, users: List[Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Map machine id / name to users.username.
    Returns (username, None) on success, or (None, reason) on failure.
    """
    raw = raw.strip()
    if not raw:
        return None, "empty user"

    raw_lower = raw.lower()
    raw_compact = re.sub(r"\s+", "", raw_lower)
    for u in users:
        fn = (getattr(u, "first_name", None) or "").strip().lower()
        ln = (getattr(u, "last_name", None) or "").strip().lower()
        full = f"{fn} {ln}".strip()
        if full and full == raw_lower:
            return u.username, None
        full_compact = re.sub(r"\s+", "", full)
        if full_compact and full_compact == raw_compact:
            return u.username, None
        if fn and raw_lower == fn:
            return u.username, None
        if (u.username or "").lower() == raw_lower:
            return u.username, None
        if str(u.id) == raw:
            return u.username, None
        # Fuzzy full-name fallback (handles minor OCR/typo differences, e.g. tirotkar/tirlotkar)
        if full:
            score = difflib.SequenceMatcher(a=full_compact, b=raw_compact).ratio()
            if score >= 0.88:
                return u.username, None

    return None, f"unknown user: {raw[:40]}"


def row_to_debug_json(norm: Dict[str, Any]) -> str:
    try:
        return json.dumps(norm, default=str)[:2000]
    except Exception:
        return str(norm)[:500]
