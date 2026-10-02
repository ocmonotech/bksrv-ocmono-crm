"""Compute when a reminder should next fire (IST), including snooze."""

from __future__ import annotations

import calendar
from datetime import date, datetime, time as dt_time, timedelta
from typing import Optional

from utils.datetime_utils import IST, as_ist, ist_now


DEFAULT_REMINDER_TIME = dt_time(9, 0)


def resolve_schedule_source(reminder, group=None):
    """Use group default schedule when the item does not have a custom schedule."""
    if group and getattr(reminder, "group_id", None) and not getattr(reminder, "use_custom_schedule", False):
        return group
    return reminder


def _reminder_time(reminder, group=None) -> dt_time:
    source = resolve_schedule_source(reminder, group)
    return source.reminder_time or DEFAULT_REMINDER_TIME


def _combine(d: date, t: dt_time) -> datetime:
    return datetime.combine(d, t, tzinfo=IST)


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _monthly_date(year: int, month: int, day_of_month: int) -> date:
    dom = max(1, min(day_of_month, _days_in_month(year, month)))
    return date(year, month, dom)


def compute_scheduled_trigger(reminder, now: Optional[datetime] = None, group=None) -> Optional[datetime]:
    """Next occurrence from the reminder schedule (ignores snooze)."""
    now = now or ist_now()
    source = resolve_schedule_source(reminder, group)
    t = _reminder_time(reminder, group)
    frequency = (source.frequency or "once").lower()

    if frequency == "once":
        if not source.reminder_date:
            return None
        return _combine(source.reminder_date, t)

    if frequency == "daily":
        candidate = _combine(now.date(), t)
        if candidate >= now:
            return candidate
        return _combine(now.date() + timedelta(days=1), t)

    if frequency == "weekly":
        target_dow = source.day_of_week or 1
        current_dow = now.isoweekday()
        days_ahead = (target_dow - current_dow) % 7
        if days_ahead == 0:
            candidate = _combine(now.date(), t)
            if candidate >= now:
                return candidate
            days_ahead = 7
        return _combine(now.date() + timedelta(days=days_ahead), t)

    if frequency == "monthly":
        dom = source.day_of_month or 1
        candidate_date = _monthly_date(now.year, now.month, dom)
        candidate = _combine(candidate_date, t)
        if candidate >= now:
            return candidate
        next_month = now.month + 1
        next_year = now.year
        if next_month > 12:
            next_month = 1
            next_year += 1
        candidate_date = _monthly_date(next_year, next_month, dom)
        return _combine(candidate_date, t)

    return None


def resolve_snooze_until(
    *,
    minutes: Optional[int] = None,
    hours: Optional[int] = None,
    days: Optional[int] = None,
    until_date: Optional[date] = None,
    until_time: Optional[str] = None,
    preset: Optional[str] = None,
    default_time: Optional[dt_time] = None,
    now: Optional[datetime] = None,
) -> datetime:
    """Resolve snooze target datetime from relative, absolute, or preset options."""
    now = now or ist_now()
    default_time = default_time or DEFAULT_REMINDER_TIME

    if preset:
        preset = preset.strip().lower()
        presets = {
            "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "3h": timedelta(hours=3),
            "1d": timedelta(days=1),
        }
        if preset in presets:
            return now + presets[preset]
        if preset == "tomorrow":
            t = default_time
            return _combine(now.date() + timedelta(days=1), t)

    if until_date is not None:
        t = default_time
        if until_time:
            try:
                t = datetime.strptime(until_time.strip(), "%H:%M").time()
            except ValueError:
                pass
        target = _combine(until_date, t)
        if target <= now:
            raise ValueError("Snooze time must be in the future")
        return target

    delta = timedelta()
    if minutes:
        delta += timedelta(minutes=minutes)
    if hours:
        delta += timedelta(hours=hours)
    if days:
        delta += timedelta(days=days)
    if delta.total_seconds() <= 0:
        raise ValueError("Provide snooze duration (minutes/hours/days), until_date, or preset")

    return now + delta


def current_period_trigger(reminder, now: Optional[datetime] = None, group=None) -> Optional[datetime]:
    """Scheduled fire time for the current period (may already be in the past)."""
    now = now or ist_now()
    source = resolve_schedule_source(reminder, group)
    t = _reminder_time(reminder, group)
    frequency = (source.frequency or "once").lower()

    if frequency == "once":
        if not source.reminder_date:
            return None
        return _combine(source.reminder_date, t)

    if frequency == "daily":
        return _combine(now.date(), t)

    if frequency == "weekly":
        target_dow = source.day_of_week or 1
        current_dow = now.isoweekday()
        days_back = (current_dow - target_dow) % 7
        return _combine(now.date() - timedelta(days=days_back), t)

    if frequency == "monthly":
        dom = source.day_of_month or 1
        return _combine(_monthly_date(now.year, now.month, dom), t)

    return None


def effective_trigger(
    reminder,
    snoozed_until: Optional[datetime],
    now: Optional[datetime] = None,
    group=None,
) -> Optional[datetime]:
    """Next datetime the client should wait for before alerting again."""
    now = now or ist_now()
    snoozed_until = as_ist(snoozed_until)

    if snoozed_until and snoozed_until > now:
        return snoozed_until

    if is_reminder_due(reminder, snoozed_until, now, group=group):
        period = current_period_trigger(reminder, now, group=group)
        if snoozed_until and snoozed_until <= now:
            return snoozed_until
        return period or now

    return compute_scheduled_trigger(reminder, now, group=group)


def is_reminder_due(
    reminder,
    snoozed_until: Optional[datetime],
    now: Optional[datetime] = None,
    group=None,
) -> bool:
    if group and not group.is_active:
        return False
    if not reminder.is_active:
        return False
    now = now or ist_now()
    snoozed_until = as_ist(snoozed_until)

    if snoozed_until and snoozed_until > now:
        return False

    if snoozed_until and snoozed_until <= now:
        return True

    period_trigger = current_period_trigger(reminder, now, group=group)
    if period_trigger is None:
        return False
    return period_trigger <= now
