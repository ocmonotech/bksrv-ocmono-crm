"""Shared reminder serialization and schedule helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.ReminderModel import Reminder
from models.ReminderGroupModel import ReminderGroup
from models.ReminderSnoozeModel import ReminderSnooze
from models.UsersModel import User
from utils.datetime_utils import as_ist, ist_now
from utils.reminder_schedule import effective_trigger, is_reminder_due, resolve_schedule_source


def parse_reminder_time(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        return None


def user_brief(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }


def get_user_snooze(db: Session, reminder_id: int, user_id: int) -> Optional[ReminderSnooze]:
    return (
        db.query(ReminderSnooze)
        .filter(ReminderSnooze.reminder_id == reminder_id, ReminderSnooze.user_id == user_id)
        .first()
    )


def schedule_fields(source) -> dict:
    return {
        "frequency": source.frequency or "once",
        "reminder_date": source.reminder_date.isoformat() if source.reminder_date else None,
        "reminder_time": source.reminder_time.strftime("%H:%M") if source.reminder_time else None,
        "day_of_week": source.day_of_week,
        "day_of_month": source.day_of_month,
    }


def reminder_item_out(reminder: Reminder, db: Session, user_id: int, group: Optional[ReminderGroup] = None) -> dict:
    schedule = resolve_schedule_source(reminder, group)
    snooze = get_user_snooze(db, reminder.id, user_id)
    snoozed_until = as_ist(snooze.snoozed_until if snooze else None)
    next_trigger = effective_trigger(reminder, snoozed_until, group=group)
    due = is_reminder_due(reminder, snoozed_until, group=group)
    is_snoozed = bool(snoozed_until and snoozed_until > ist_now())

    return {
        "id": reminder.id,
        "sort_order": reminder.sort_order or 0,
        "title": reminder.title,
        "use_custom_schedule": bool(reminder.use_custom_schedule),
        "is_active": bool(reminder.is_active),
        **schedule_fields(schedule),
        "next_trigger_at": next_trigger,
        "is_due": due,
        "is_snoozed": is_snoozed,
        "snoozed_until": snoozed_until,
    }


def reminder_to_out(reminder: Reminder, db: Session, user_id: int) -> dict:
    group = reminder.group if getattr(reminder, "group", None) else None
    schedule = resolve_schedule_source(reminder, group)
    snooze = get_user_snooze(db, reminder.id, user_id)
    snoozed_until = as_ist(snooze.snoozed_until if snooze else None)
    next_trigger = effective_trigger(reminder, snoozed_until, group=group)
    due = is_reminder_due(reminder, snoozed_until, group=group)
    is_snoozed = bool(snoozed_until and snoozed_until > ist_now())

    return {
        "id": reminder.id,
        "user_id": reminder.user_id,
        "group_id": reminder.group_id,
        "group_name": group.name if group else None,
        "sort_order": reminder.sort_order or 0,
        "use_custom_schedule": bool(reminder.use_custom_schedule),
        "created_by_id": reminder.created_by_id,
        "created_by": user_brief(reminder.created_by) if getattr(reminder, "created_by", None) else None,
        "title": reminder.title,
        "notes": reminder.notes if not group else (group.notes or reminder.notes),
        **schedule_fields(schedule),
        "is_active": bool(reminder.is_active),
        "assigned_users": [user_brief(u) for u in (reminder.assigned_users or [])],
        "next_trigger_at": next_trigger,
        "is_due": due,
        "is_snoozed": is_snoozed,
        "snoozed_until": snoozed_until,
        "created_at": reminder.created_at,
        "updated_at": reminder.updated_at,
    }


def group_to_out(group: ReminderGroup, db: Session, user_id: int) -> dict:
    items = sorted(group.reminders or [], key=lambda r: r.sort_order or 0)
    return {
        "id": group.id,
        "name": group.name,
        "notes": group.notes,
        **schedule_fields(group),
        "is_active": bool(group.is_active),
        "created_by_id": group.created_by_id,
        "created_by": user_brief(group.created_by) if getattr(group, "created_by", None) else None,
        "assigned_users": [user_brief(u) for u in (group.assigned_users or [])],
        "items": [reminder_item_out(item, db, user_id, group) for item in items],
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


def resolve_assignees(db: Session, assignee_ids: List[int]) -> List[User]:
    users = (
        db.query(User)
        .filter(User.id.in_(assignee_ids), User.is_deleted == False)
        .all()
    )
    if not users:
        raise HTTPException(status_code=400, detail="No valid assignees found")
    return users


def user_can_access_reminder(reminder: Reminder, user_id: int) -> bool:
    if reminder.created_by_id == user_id or reminder.user_id == user_id:
        return True
    if any(u.id == user_id for u in (reminder.assigned_users or [])):
        return True
    group = getattr(reminder, "group", None)
    if group:
        if group.created_by_id == user_id:
            return True
        if any(u.id == user_id for u in (group.assigned_users or [])):
            return True
    return False


def user_can_access_group(group: ReminderGroup, user_id: int) -> bool:
    if group.created_by_id == user_id:
        return True
    return any(u.id == user_id for u in (group.assigned_users or []))


def apply_item_schedule(reminder: Reminder, item, group_defaults, *, is_update: bool = False) -> None:
    title = getattr(item, "title", None)
    if title is not None and str(title).strip():
        reminder.title = str(title).strip()
    elif not is_update:
        reminder.title = str(title or "").strip()

    if getattr(item, "use_custom_schedule", None) is not None or not is_update:
        reminder.use_custom_schedule = bool(item.use_custom_schedule)

    if reminder.use_custom_schedule:
        reminder.frequency = item.frequency or getattr(group_defaults, "frequency", "once")
        reminder.reminder_date = item.reminder_date
        reminder.reminder_time = parse_reminder_time(item.reminder_time)
        reminder.day_of_week = item.day_of_week
        reminder.day_of_month = item.day_of_month
    else:
        reminder.frequency = None
        reminder.reminder_date = None
        reminder.reminder_time = None
        reminder.day_of_week = None
        reminder.day_of_month = None
