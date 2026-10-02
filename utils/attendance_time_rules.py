"""Compute daily attendance metrics from punch list + AttendanceSettings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from models.AttendanceSettingsModel import AttendanceSettings


def _combine(d: date, t: time) -> datetime:
    return datetime.combine(d, t)


def _overlap_hours(seg_start: datetime, seg_end: datetime, win_start: datetime, win_end: datetime) -> float:
    if seg_end <= seg_start or win_end <= win_start:
        return 0.0
    s = max(seg_start, win_start)
    e = min(seg_end, win_end)
    if e <= s:
        return 0.0
    return (e - s).total_seconds() / 3600.0


@dataclass
class DayAttendanceMetrics:
    hours_morning: float
    hours_afternoon: float
    hours_total_span: float
    late: bool
    half_day: bool
    first_half_short: bool
    second_half_short: bool
    ot_checkin_minutes: int
    ot_checkout_minutes: int


def compute_day_metrics(
    day_punches: List[datetime],
    d: date,
    s: "AttendanceSettings",
) -> DayAttendanceMetrics:
    """
    day_punches: sorted non-empty datetimes on calendar day ``d`` (naive local wall clock).
    """
    first = day_punches[0]
    last = day_punches[-1]

    t_on1 = _combine(d, s.on_duty_first_half)
    t_off1 = _combine(d, s.off_duty_first_half)
    t_on2 = _combine(d, s.on_duty_second_half)
    t_off2 = _combine(d, s.off_duty_second_half)

    if t_off1 <= t_on1:
        t_off1 = t_on1 + timedelta(hours=1)
    if t_off2 <= t_on2:
        t_off2 = t_on2 + timedelta(hours=1)

    hours_morning = _overlap_hours(first, last, t_on1, t_off1)
    hours_afternoon = _overlap_hours(first, last, t_on2, t_off2)
    hours_total_span = max(0.0, (last - first).total_seconds() / 3600.0)

    late = first.time() > s.late_mark_after

    min_m = float(s.half_day_min_hours_first_half)
    min_a = float(s.half_day_min_hours_second_half)
    first_half_short = hours_morning < min_m
    second_half_short = hours_afternoon < min_a

    # Session-presence policy:
    # - Full day when attendance clearly spans both halves
    #   (check-in in first-half window and check-out reaches second-half start or later)
    # - Half day when attendance is only in one half
    # - Half day when attendance is outside both halves
    in_first_window = t_on1 <= first <= t_off1
    reaches_second_half = last >= t_on2

    has_first_window_punch = any(t_on1 <= p <= t_off1 for p in day_punches)
    has_second_half_presence = any(p >= t_on2 for p in day_punches)

    if in_first_window and reaches_second_half:
        half_day = False
    elif has_first_window_punch and has_second_half_presence:
        half_day = False
    elif has_first_window_punch ^ has_second_half_presence:
        half_day = True
    else:
        half_day = True

    ot_in = 0
    if s.overtime_checkin_before is not None and first < t_on1:
        ot_in = int((t_on1 - first).total_seconds() // 60)

    ot_out = 0
    if s.overtime_checkout_after is not None:
        t_ot = _combine(d, s.overtime_checkout_after)
        if last > t_ot:
            ot_out = int((last - t_ot).total_seconds() // 60)

    return DayAttendanceMetrics(
        hours_morning=round(hours_morning, 2),
        hours_afternoon=round(hours_afternoon, 2),
        hours_total_span=round(hours_total_span, 2),
        late=late,
        half_day=half_day,
        first_half_short=first_half_short,
        second_half_short=second_half_short,
        ot_checkin_minutes=ot_in,
        ot_checkout_minutes=ot_out,
    )
