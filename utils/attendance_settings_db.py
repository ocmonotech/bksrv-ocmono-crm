"""Load or seed the single attendance_settings row (id=1)."""

from __future__ import annotations

from datetime import time

from sqlalchemy.orm import Session

from models.AttendanceSettingsModel import AttendanceSettings

SETTINGS_ID = 1


def _defaults_row() -> AttendanceSettings:
    return AttendanceSettings(
        id=SETTINGS_ID,
        on_duty_first_half=time(10, 0),
        off_duty_first_half=time(13, 30),
        on_duty_second_half=time(14, 0),
        off_duty_second_half=time(19, 0),
        half_day_min_hours_first_half=3.5,
        half_day_min_hours_second_half=3.5,
        late_mark_after=time(10, 30),
        overtime_checkin_before=None,
        overtime_checkout_after=None,
    )


def get_or_create_settings(db: Session) -> AttendanceSettings:
    row = db.query(AttendanceSettings).filter(AttendanceSettings.id == SETTINGS_ID).first()
    if row is None:
        row = _defaults_row()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row
