"""Org-wide attendance policy used by punch-machine reports (single logical row, id=1)."""

from sqlalchemy import Column, Integer, String, Time, Float, DateTime
from database import Base
from utils.datetime_utils import ist_now


class AttendanceSettings(Base):
    __tablename__ = "attendance_settings"

    id = Column(Integer, primary_key=True, index=True)
    # Duty windows (wall clock, same calendar day)
    on_duty_first_half = Column(Time, nullable=False)
    off_duty_first_half = Column(Time, nullable=False)
    on_duty_second_half = Column(Time, nullable=False)
    off_duty_second_half = Column(Time, nullable=False)
    # Minimum hours actually present inside each half-window to avoid a "short half" / half-day flag
    half_day_min_hours_first_half = Column(Float, nullable=False)
    half_day_min_hours_second_half = Column(Float, nullable=False)
    # First punch after this time counts as a late mark for the day
    late_mark_after = Column(Time, nullable=False)
    # Overtime: if set, early arrival before morning on-duty counts as OT-in minutes
    overtime_checkin_before = Column(Time, nullable=True)
    # Overtime: if set, departure after this time counts as OT-out minutes (from this timestamp to last punch)
    overtime_checkout_after = Column(Time, nullable=True)

    updated_at = Column(DateTime(timezone=True), default=ist_now)
    updated_by_username = Column(String(50), nullable=True)
