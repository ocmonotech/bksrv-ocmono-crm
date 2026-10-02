# Reminder groups: shared schedule, notes, assignees, and multiple reminder items
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models.ReminderModel import Reminder
from models.ReminderGroupModel import ReminderGroup
from models.UsersModel import User
from schemas.ReminderGroupSchema import (
    ReminderGroupCreate,
    ReminderGroupUpdate,
    ReminderGroupItemCreate,
    ReminderGroupItemPatch,
)
from routers.auth import get_current_user
from utils.notifications import create_notification
from utils.reminder_common import (
    apply_item_schedule,
    group_to_out,
    parse_reminder_time,
    reminder_item_out,
    resolve_assignees,
    user_can_access_group,
)
from typing import Optional, List


router = APIRouter(prefix="/reminders/groups", tags=["Reminder Groups"])


def _groups_for_user_query(db: Session, user_id: int):
    return (
        db.query(ReminderGroup)
        .outerjoin(ReminderGroup.assigned_users)
        .filter(
            or_(
                ReminderGroup.created_by_id == user_id,
                User.id == user_id,
            )
        )
        .distinct()
    )


def _load_group(db: Session, group_id: int) -> Optional[ReminderGroup]:
    return (
        db.query(ReminderGroup)
        .options(
            joinedload(ReminderGroup.created_by),
            joinedload(ReminderGroup.assigned_users),
            joinedload(ReminderGroup.reminders),
        )
        .filter(ReminderGroup.id == group_id)
        .first()
    )


def _next_item_sort_order(group: ReminderGroup) -> int:
    orders = [r.sort_order or 0 for r in (group.reminders or [])]
    return (max(orders) + 1) if orders else 1


def _get_group_item_or_404(group: ReminderGroup, item_id: int) -> Reminder:
    reminder = next((r for r in (group.reminders or []) if r.id == item_id), None)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder item not found in group")
    return reminder


def _sync_group_assignees_to_items(group: ReminderGroup, assignees: List[User]) -> None:
    for reminder in group.reminders or []:
        reminder.assigned_users = assignees
        if assignees:
            reminder.user_id = assignees[0].id


def _build_group_from_create(data: ReminderGroupCreate, current_user: User, assignees: List[User]) -> ReminderGroup:
    group = ReminderGroup(
        name=data.name.strip(),
        notes=data.notes if data.notes else None,
        frequency=data.frequency,
        reminder_date=data.reminder_date,
        reminder_time=parse_reminder_time(data.reminder_time),
        day_of_week=data.day_of_week,
        day_of_month=data.day_of_month,
        created_by_id=current_user.id,
        is_active=True,
    )
    group.assigned_users = assignees

    for idx, item in enumerate(data.items):
        reminder = Reminder(
            user_id=assignees[0].id,
            created_by_id=current_user.id,
            group_id=None,
            sort_order=idx + 1,
            is_active=True,
        )
        apply_item_schedule(reminder, item, data)
        reminder.assigned_users = assignees
        group.reminders.append(reminder)

    return group


@router.get("/list", response_model=List[dict])
def list_reminder_groups(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    is_active: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """List reminder groups visible to the current user."""
    query = _groups_for_user_query(db, current_user.id)
    if is_active is not None:
        query = query.filter(ReminderGroup.is_active == is_active)
    groups = (
        query.options(
            joinedload(ReminderGroup.created_by),
            joinedload(ReminderGroup.assigned_users),
            joinedload(ReminderGroup.reminders),
        )
        .order_by(ReminderGroup.created_at.desc())
        .limit(limit)
        .all()
    )
    return [group_to_out(g, db, current_user.id) for g in groups]


@router.get("/{group_id}", response_model=dict)
def get_reminder_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = _load_group(db, group_id)
    if not group or not user_can_access_group(group, current_user.id):
        raise HTTPException(status_code=404, detail="Reminder group not found")
    return group_to_out(group, db, current_user.id)


@router.post("/create", response_model=dict, status_code=201)
def create_reminder_group(
    data: ReminderGroupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assignee_ids = data.assignee_ids if data.assignee_ids else [current_user.id]
    assignees = resolve_assignees(db, assignee_ids)

    group = _build_group_from_create(data, current_user, assignees)
    db.add(group)
    db.commit()
    group = _load_group(db, group.id)

    for user in assignees:
        if user.id != current_user.id:
            create_notification(
                db,
                user.id,
                f"New reminder group assigned: {group.name}",
                notif_type="reminder",
                target_url=f"/reminders/groups/{group.id}",
                entity_id=group.id,
            )

    return group_to_out(group, db, current_user.id)


@router.put("/update/{group_id}", response_model=dict)
def update_reminder_group(
    group_id: int,
    data: ReminderGroupUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = _load_group(db, group_id)
    if not group or not user_can_access_group(group, current_user.id):
        raise HTTPException(status_code=404, detail="Reminder group not found")

    old_assigned_ids = {u.id for u in group.assigned_users}
    payload = data.model_dump(exclude_unset=True)
    assignee_ids = payload.pop("assignee_ids", None)
    payload.pop("items", None)
    items_to_update = data.items if "items" in data.model_fields_set else None
    reminder_time_str = payload.pop("reminder_time", None)

    for key, value in payload.items():
        setattr(group, key, value)

    if reminder_time_str is not None:
        group.reminder_time = parse_reminder_time(reminder_time_str)

    if assignee_ids is not None:
        assignees = resolve_assignees(db, assignee_ids) if assignee_ids else []
        group.assigned_users = assignees
        _sync_group_assignees_to_items(group, assignees)

    if items_to_update is not None:
        existing_by_id = {r.id: r for r in (group.reminders or [])}
        kept_ids = set()

        for idx, item in enumerate(items_to_update):
            if item.id:
                reminder = existing_by_id.get(item.id)
                if not reminder:
                    raise HTTPException(status_code=400, detail=f"Reminder item {item.id} not found in group")
                kept_ids.add(item.id)
            else:
                if not item.title or not str(item.title).strip():
                    raise HTTPException(status_code=400, detail="New reminder items need a title")
                assignees = group.assigned_users or [current_user]
                reminder = Reminder(
                    user_id=assignees[0].id,
                    created_by_id=group.created_by_id or current_user.id,
                    is_active=True,
                )
                group.reminders.append(reminder)

            reminder.sort_order = idx + 1
            apply_item_schedule(reminder, item, group, is_update=bool(item.id))
            reminder.assigned_users = group.assigned_users
            if group.assigned_users:
                reminder.user_id = group.assigned_users[0].id

        for reminder in list(group.reminders or []):
            if reminder.id and reminder.id not in kept_ids:
                db.delete(reminder)

    db.commit()
    group = _load_group(db, group_id)

    if assignee_ids is not None:
        new_assigned_ids = {u.id for u in group.assigned_users}
        newly_assigned = new_assigned_ids - old_assigned_ids
        for user in group.assigned_users or []:
            if user.id in newly_assigned and user.id != current_user.id:
                create_notification(
                    db,
                    user.id,
                    f"You were assigned a reminder group: {group.name}",
                    notif_type="reminder",
                    target_url=f"/reminders/groups/{group.id}",
                    entity_id=group.id,
                )

    return group_to_out(group, db, current_user.id)


@router.post("/{group_id}/items", response_model=dict, status_code=201)
def add_reminder_to_group(
    group_id: int,
    data: ReminderGroupItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a reminder item to an existing group."""
    group = _load_group(db, group_id)
    if not group or not user_can_access_group(group, current_user.id):
        raise HTTPException(status_code=404, detail="Reminder group not found")

    if not data.title or not str(data.title).strip():
        raise HTTPException(status_code=400, detail="Title is required")

    assignees = group.assigned_users or [current_user]
    reminder = Reminder(
        user_id=assignees[0].id,
        created_by_id=current_user.id,
        sort_order=_next_item_sort_order(group),
        is_active=True,
    )
    apply_item_schedule(reminder, data, group)
    reminder.assigned_users = assignees
    group.reminders.append(reminder)

    db.commit()
    db.refresh(reminder)
    return reminder_item_out(reminder, db, current_user.id, group)


@router.put("/{group_id}/items/{item_id}", response_model=dict)
def update_reminder_in_group(
    group_id: int,
    item_id: int,
    data: ReminderGroupItemPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a single reminder item within a group."""
    group = _load_group(db, group_id)
    if not group or not user_can_access_group(group, current_user.id):
        raise HTTPException(status_code=404, detail="Reminder group not found")

    reminder = _get_group_item_or_404(group, item_id)

    apply_item_schedule(reminder, data, group, is_update=True)

    if data.is_active is not None:
        reminder.is_active = data.is_active
    if data.sort_order is not None:
        reminder.sort_order = data.sort_order

    reminder.assigned_users = group.assigned_users
    if group.assigned_users:
        reminder.user_id = group.assigned_users[0].id

    db.commit()
    db.refresh(reminder)
    return reminder_item_out(reminder, db, current_user.id, group)


@router.delete("/delete/{group_id}", status_code=204)
def delete_reminder_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.query(ReminderGroup).filter(ReminderGroup.id == group_id).first()
    if not group or not user_can_access_group(group, current_user.id):
        raise HTTPException(status_code=404, detail="Reminder group not found")
    db.delete(group)
    db.commit()
    return None
