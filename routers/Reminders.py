# Reminders: user-set reminders (daily, weekly, monthly, once) with dates
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, or_
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models.ReminderModel import Reminder
from models.ReminderSnoozeModel import ReminderSnooze
from models.UsersModel import User
from schemas.ReminderSchema import ReminderCreate, ReminderUpdate, ReminderOut, ReminderSnoozeRequest
from routers.auth import get_current_user
from utils.notifications import create_notification
from utils.reminder_schedule import resolve_snooze_until, resolve_schedule_source
from utils.reminder_common import (
    get_user_snooze,
    parse_reminder_time,
    reminder_to_out,
    resolve_assignees,
    user_can_access_reminder,
)
from utils.datetime_utils import ist_now
from typing import Optional, List


router = APIRouter(prefix="/reminders", tags=["Reminders"])


def _assigned_reminders_query(db: Session, user_id: int):
    return (
        db.query(Reminder)
        .options(joinedload(Reminder.group), joinedload(Reminder.created_by), joinedload(Reminder.assigned_users))
        .outerjoin(Reminder.assigned_users)
        .filter(
            or_(
                User.id == user_id,
                Reminder.user_id == user_id,
            )
        )
        .distinct()
    )


@router.get("/due", response_model=List[dict])
def list_due_reminders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
):
    """Reminders that should alert now for the current user (alarm-style)."""
    rows = (
        _assigned_reminders_query(db, current_user.id)
        .filter(Reminder.is_active == True)
        .order_by(Reminder.created_at.desc())
        .limit(limit)
        .all()
    )
    due = []
    for r in rows:
        out = reminder_to_out(r, db, current_user.id)
        if out["is_due"]:
            due.append(out)
    due.sort(key=lambda x: x["next_trigger_at"] or ist_now())
    return due


@router.get("/list", response_model=List[dict])
def list_reminders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    frequency: Optional[str] = Query(None, description="daily | weekly | monthly | once"),
    is_active: Optional[bool] = Query(None),
    group_id: Optional[int] = Query(None, description="Filter by reminder group"),
    standalone_only: Optional[bool] = Query(None, description="true = only reminders not in a group"),
    limit: int = Query(100, ge=1, le=500),
):
    """List reminders assigned to the current user. Filter by frequency and is_active."""
    query = _assigned_reminders_query(db, current_user.id)
    if frequency:
        query = query.filter(Reminder.frequency == frequency.lower())
    if is_active is not None:
        query = query.filter(Reminder.is_active == is_active)
    if group_id is not None:
        query = query.filter(Reminder.group_id == group_id)
    if standalone_only:
        query = query.filter(Reminder.group_id.is_(None))
    rows = query.order_by(
        case((Reminder.reminder_date.is_(None), 1), else_=0).asc(),
        Reminder.reminder_date.desc(),
        Reminder.created_at.desc(),
    ).limit(limit).all()
    return [reminder_to_out(r, db, current_user.id) for r in rows]


@router.get("/{reminder_id}", response_model=dict)
def get_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reminder = (
        db.query(Reminder)
        .options(joinedload(Reminder.group), joinedload(Reminder.created_by), joinedload(Reminder.assigned_users))
        .filter(Reminder.id == reminder_id)
        .first()
    )
    if not reminder or not user_can_access_reminder(reminder, current_user.id):
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder_to_out(reminder, db, current_user.id)


@router.post("/create", response_model=dict, status_code=201)
def create_reminder(
    data: ReminderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assignee_ids = data.assignee_ids if data.assignee_ids else [current_user.id]
    assignees = resolve_assignees(db, assignee_ids)

    reminder = Reminder(
        user_id=assignees[0].id,
        created_by_id=current_user.id,
        title=data.title.strip(),
        notes=data.notes if data.notes else None,
        frequency=data.frequency,
        reminder_date=data.reminder_date,
        reminder_time=parse_reminder_time(data.reminder_time),
        day_of_week=data.day_of_week,
        day_of_month=data.day_of_month,
        is_active=True,
    )
    reminder.assigned_users = assignees
    db.add(reminder)
    db.commit()
    db.refresh(reminder)

    for user in assignees:
        if user.id != current_user.id:
            create_notification(
                db,
                user.id,
                f"New reminder assigned: {reminder.title}",
                notif_type="reminder",
                target_url=f"/reminders/{reminder.id}",
                entity_id=reminder.id,
            )

    return reminder_to_out(reminder, db, current_user.id)


@router.put("/update/{reminder_id}", response_model=dict)
def update_reminder(
    reminder_id: int,
    data: ReminderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reminder = (
        db.query(Reminder)
        .options(joinedload(Reminder.group), joinedload(Reminder.assigned_users))
        .filter(Reminder.id == reminder_id)
        .first()
    )
    if not reminder or not user_can_access_reminder(reminder, current_user.id):
        raise HTTPException(status_code=404, detail="Reminder not found")

    old_assigned_ids = {u.id for u in reminder.assigned_users}
    payload = data.model_dump(exclude_unset=True)
    assignee_ids = payload.pop("assignee_ids", None)
    reminder_time_str = payload.pop("reminder_time", None)

    for key, value in payload.items():
        setattr(reminder, key, value)

    if reminder_time_str is not None:
        reminder.reminder_time = parse_reminder_time(reminder_time_str)

    if assignee_ids is not None:
        assignees = resolve_assignees(db, assignee_ids) if assignee_ids else []
        reminder.assigned_users = assignees
        if assignees:
            reminder.user_id = assignees[0].id

    db.commit()
    db.refresh(reminder)

    if assignee_ids is not None:
        new_assigned_ids = {u.id for u in reminder.assigned_users}
        newly_assigned = new_assigned_ids - old_assigned_ids
        for user in reminder.assigned_users or []:
            if user.id in newly_assigned and user.id != current_user.id:
                create_notification(
                    db,
                    user.id,
                    f"You were assigned a reminder: {reminder.title}",
                    notif_type="reminder",
                    target_url=f"/reminders/{reminder.id}",
                    entity_id=reminder.id,
                )

    return reminder_to_out(reminder, db, current_user.id)


@router.post("/{reminder_id}/snooze", response_model=dict)
def snooze_reminder(
    reminder_id: int,
    data: ReminderSnoozeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Snooze a reminder for the current user; it will alert again after the chosen interval."""
    reminder = (
        db.query(Reminder)
        .options(joinedload(Reminder.group))
        .filter(Reminder.id == reminder_id)
        .first()
    )
    if not reminder or not user_can_access_reminder(reminder, current_user.id):
        raise HTTPException(status_code=404, detail="Reminder not found")

    schedule = resolve_schedule_source(reminder, reminder.group)
    try:
        snoozed_until = resolve_snooze_until(
            minutes=data.minutes,
            hours=data.hours,
            days=data.days,
            until_date=data.until_date,
            until_time=data.until_time,
            preset=data.preset,
            default_time=schedule.reminder_time,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    snooze = get_user_snooze(db, reminder_id, current_user.id)
    if snooze:
        snooze.snoozed_until = snoozed_until
    else:
        snooze = ReminderSnooze(
            reminder_id=reminder_id,
            user_id=current_user.id,
            snoozed_until=snoozed_until,
        )
        db.add(snooze)

    db.commit()
    db.refresh(reminder)
    return reminder_to_out(reminder, db, current_user.id)


@router.post("/{reminder_id}/dismiss", response_model=dict)
def dismiss_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dismiss the current alert. One-time reminders deactivate; recurring ones wait for the next schedule."""
    reminder = (
        db.query(Reminder)
        .options(joinedload(Reminder.group))
        .filter(Reminder.id == reminder_id)
        .first()
    )
    if not reminder or not user_can_access_reminder(reminder, current_user.id):
        raise HTTPException(status_code=404, detail="Reminder not found")

    snooze = get_user_snooze(db, reminder_id, current_user.id)
    if snooze:
        db.delete(snooze)

    schedule = resolve_schedule_source(reminder, reminder.group)
    if (schedule.frequency or "once").lower() == "once":
        reminder.is_active = False

    db.commit()
    db.refresh(reminder)
    return reminder_to_out(reminder, db, current_user.id)


@router.delete("/delete/{reminder_id}", status_code=204)
def delete_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if not reminder or not user_can_access_reminder(reminder, current_user.id):
        raise HTTPException(status_code=404, detail="Reminder not found")
    db.delete(reminder)
    db.commit()
    return None
