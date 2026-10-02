"""Admin APIs for org-wide attendance policy (duty windows, half-day thresholds, late, OT)."""

from __future__ import annotations

import re
from datetime import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models.AttendanceSettingsModel import AttendanceSettings
from models.UsersModel import User
from routers.auth import get_current_user
from utils.attendance_settings_db import get_or_create_settings
from utils.datetime_utils import ist_now

router = APIRouter(tags=["Attendance Settings"])

HM_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


def _parse_hm(value: str, field: str) -> time:
    if not value or not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{field} must be a string HH:MM")
    m = HM_RE.match(value.strip())
    if not m:
        raise HTTPException(status_code=400, detail=f"{field} must be HH:MM (24h)")
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        raise HTTPException(status_code=400, detail=f"{field} has invalid time")
    return time(h, mi)


def _fmt_t(t: Optional[time]) -> Optional[str]:
    if t is None:
        return None
    return t.strftime("%H:%M")


def settings_to_dict(row) -> dict:
    return {
        "id": row.id,
        "on_duty_first_half": _fmt_t(row.on_duty_first_half),
        "off_duty_first_half": _fmt_t(row.off_duty_first_half),
        "on_duty_second_half": _fmt_t(row.on_duty_second_half),
        "off_duty_second_half": _fmt_t(row.off_duty_second_half),
        "half_day_min_hours_first_half": float(row.half_day_min_hours_first_half),
        "half_day_min_hours_second_half": float(row.half_day_min_hours_second_half),
        "late_mark_after": _fmt_t(row.late_mark_after),
        "overtime_checkin_before": _fmt_t(row.overtime_checkin_before),
        "overtime_checkout_after": _fmt_t(row.overtime_checkout_after),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by_username": row.updated_by_username,
    }


class AttendanceSettingsUpdate(BaseModel):
    on_duty_first_half: str = Field(..., description="HH:MM, start of first half")
    off_duty_first_half: str = Field(..., description="HH:MM, end of first half")
    on_duty_second_half: str = Field(..., description="HH:MM, start of second half")
    off_duty_second_half: str = Field(..., description="HH:MM, end of second half")
    half_day_min_hours_first_half: float = Field(..., ge=0.0, le=12.0)
    half_day_min_hours_second_half: float = Field(..., ge=0.0, le=12.0)
    late_mark_after: str = Field(..., description="HH:MM; first punch after this is a late mark")
    overtime_checkin_before: Optional[str] = Field(
        None,
        description="If set, OT-in minutes = time from first punch to morning on-duty when first punch is before on-duty",
    )
    overtime_checkout_after: Optional[str] = Field(
        None,
        description="If set, OT-out minutes = time from this clock time to last punch when last punch is after this time",
    )


def _require_admin(user: User) -> None:
    if user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access denied")


@router.get("/admin/attendance/settings")
def get_attendance_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    row = get_or_create_settings(db)
    return {"settings": settings_to_dict(row)}


@router.put("/admin/attendance/settings")
def update_attendance_settings(
    body: AttendanceSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    row = get_or_create_settings(db)

    row.on_duty_first_half = _parse_hm(body.on_duty_first_half, "on_duty_first_half")
    row.off_duty_first_half = _parse_hm(body.off_duty_first_half, "off_duty_first_half")
    row.on_duty_second_half = _parse_hm(body.on_duty_second_half, "on_duty_second_half")
    row.off_duty_second_half = _parse_hm(body.off_duty_second_half, "off_duty_second_half")

    if row.off_duty_first_half <= row.on_duty_first_half:
        raise HTTPException(status_code=400, detail="off_duty_first_half must be after on_duty_first_half")
    if row.off_duty_second_half <= row.on_duty_second_half:
        raise HTTPException(status_code=400, detail="off_duty_second_half must be after on_duty_second_half")
    if row.on_duty_second_half < row.off_duty_first_half:
        pass

    row.half_day_min_hours_first_half = body.half_day_min_hours_first_half
    row.half_day_min_hours_second_half = body.half_day_min_hours_second_half
    row.late_mark_after = _parse_hm(body.late_mark_after, "late_mark_after")

    ot_in_raw = (body.overtime_checkin_before or "").strip() if body.overtime_checkin_before is not None else ""
    ot_out_raw = (body.overtime_checkout_after or "").strip() if body.overtime_checkout_after is not None else ""
    row.overtime_checkin_before = (
        _parse_hm(ot_in_raw, "overtime_checkin_before") if ot_in_raw else None
    )
    row.overtime_checkout_after = (
        _parse_hm(ot_out_raw, "overtime_checkout_after") if ot_out_raw else None
    )

    row.updated_at = ist_now()
    row.updated_by_username = current_user.username
    db.commit()
    db.refresh(row)
    return {"settings": settings_to_dict(row), "message": "Attendance settings updated"}
