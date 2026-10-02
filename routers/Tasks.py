# Tasks router: assignment-scoped tasks (list/detail/CRUD) + lead tasks (by-lead)
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from utils.activity import set_activity_description, describe_created, describe_updated, describe_deleted
from sqlalchemy import or_, func, asc, desc, case
from database import get_db
from models.LeadTaskModel import LeadTask
from models.TaskModel import Task
from models.UsersModel import User
from models.ClientModel import Client
from models.ProjectModel import Project
from models.AssignmentModel import Assignment
from models.UserGroupModel import UserGroup
from schemas.TaskSchema import (
    LeadTaskCreate,
    LeadTaskUpdate,
    LeadTaskOut,
    TaskCreate,
    TaskUpdate,
    TaskOut,
    TaskAssigneeOut,
    PaginatedTaskOut,
)
from routers.auth import get_current_user, get_admin_user
from typing import Optional, List
from datetime import date, datetime
from utils.datetime_utils import ist_now
from utils.notifications import create_notification

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def _user_display_name(user: Optional[User]) -> str:
    if not user:
        return ""
    return f"{user.first_name or ''} {user.last_name or ''}".strip() or (user.username or "")


def _task_to_out(t: Task) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "description": t.description,
        "client_id": t.client_id,
        "project_id": t.project_id,
        "assignment_id": t.assignment_id,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "priority": t.priority or "Normal",
        "status": t.status or "Pending",
        "estimated_hours": float(t.estimated_hours or 0),
        "actual_hours": float(t.actual_hours or 0),
        "brief_link": t.brief_link,
        "resources_link": t.resources_link,
        "client_folder_link": t.client_folder_link,
        "work_link": t.work_link,
        "is_active": t.is_active if t.is_active is not None else True,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
        "client_name": t.client.client_name if t.client else None,
        "project_name": t.project.project_name if t.project else None,
        "project_code": t.project.project_code if t.project else None,
        "assignment_title": t.assignment.title if t.assignment else None,
        "assigned_users": [
            {"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name}
            for u in (t.assigned_users or [])
        ],
    }


def _employee_task_filter(current_user: User):
    return or_(
        Task.assigned_users.any(User.id == current_user.id),
        Assignment.created_by == current_user.username,
        Assignment.assigned_by == current_user.username,
    )


def _build_task_list_query(
    db: Session,
    view: Optional[str],
    search: Optional[str],
    status: Optional[List[str]],
    priority: Optional[List[str]],
    date_from: Optional[date],
    date_to: Optional[date],
    client_id: Optional[int],
    project_id: Optional[int],
    assignment_id: Optional[int],
    assignee_ids: Optional[List[int]],
):
    query = (
        db.query(Task)
        .filter(Task.is_deleted == False)
        .join(Client, Task.client_id == Client.id)
        .outerjoin(Project, Task.project_id == Project.id)
        .outerjoin(Assignment, Task.assignment_id == Assignment.id)
    )
    if view == "active":
        query = query.filter(Task.is_active == True)
    elif view == "inactive":
        query = query.filter(Task.is_active == False)
    if search:
        term = f"%{search}%"
        query = query.outerjoin(Task.assigned_users).filter(
            or_(
                Task.title.ilike(term),
                Task.description.ilike(term),
                Client.client_name.ilike(term),
                Assignment.title.ilike(term),
                Project.project_name.ilike(term),
                User.first_name.ilike(term),
                User.last_name.ilike(term),
                User.username.ilike(term),
            )
        ).distinct()
    if status:
        query = query.filter(Task.status.in_(status))
    if priority:
        query = query.filter(Task.priority.in_(priority))
    if date_from:
        query = query.filter(Task.due_date >= date_from)
    if date_to:
        query = query.filter(Task.due_date <= date_to)
    if client_id:
        query = query.filter(Task.client_id == client_id)
    if project_id is not None:
        query = query.filter(Task.project_id == project_id)
    if assignment_id:
        query = query.filter(Task.assignment_id == assignment_id)
    if assignee_ids:
        query = query.join(Task.assigned_users).filter(User.id.in_(assignee_ids)).distinct()
    return query


# ----- Assignment tasks: list with filters, sort, pagination, stats -----
@router.get("", response_model=PaginatedTaskOut)
def list_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: Optional[str] = Query(None),
    view: Optional[str] = Query("active", description="active | inactive | all"),
    status: Optional[List[str]] = Query(None),
    priority: Optional[List[str]] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    assignee_ids: Optional[List[int]] = Query(None),
    client_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    assignment_id: Optional[int] = Query(None),
    sort_by: str = Query("due_date"),
    order: str = Query("desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    query = _build_task_list_query(
        db, view, search, status, priority, date_from, date_to,
        client_id, project_id, assignment_id, assignee_ids,
    )
    if current_user.role == "Employee":
        query = query.filter(_employee_task_filter(current_user)).distinct()
    total = query.count()

    # Stats: conditional aggregates on same filtered set (subquery to avoid double-count from joins)
    subq = query.with_entities(Task.id).distinct().subquery()
    stats_row = (
        db.query(
            func.count(Task.id),
            func.coalesce(func.sum(case((Task.status == "Pending", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Task.status == "In Progress", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Task.status == "Completed", 1), else_=0)), 0),
            func.coalesce(func.sum(Task.estimated_hours), 0),
            func.coalesce(func.sum(Task.actual_hours), 0),
        )
        .filter(Task.id.in_(subq))
        .first()
    )
    if stats_row:
        total_pending = int(stats_row[1] or 0)
        total_in_progress = int(stats_row[2] or 0)
        total_completed = int(stats_row[3] or 0)
        total_estimated_hours = float(stats_row[4] or 0)
        total_actual_hours = float(stats_row[5] or 0)
    else:
        total_pending = total_in_progress = total_completed = 0
        total_estimated_hours = total_actual_hours = 0.0

    sort_col = getattr(Task, sort_by, Task.due_date)
    if order == "asc":
        query = query.order_by(asc(sort_col))
    else:
        query = query.order_by(desc(sort_col))
    offset = (page - 1) * limit
    rows = query.offset(offset).limit(limit).all()
    items = [_task_to_out(r) for r in rows]

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pending": total_pending,
        "total_in_progress": total_in_progress,
        "total_completed": total_completed,
        "total_estimated_hours": total_estimated_hours,
        "total_actual_hours": total_actual_hours,
    }


# Get single task (must be after list so /tasks/{id} doesn't catch /tasks/by-lead)
@router.get("/stats")
def task_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    view: Optional[str] = Query("active"),
    status: Optional[List[str]] = Query(None),
    priority: Optional[List[str]] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
):
    query = db.query(Task).filter(Task.is_deleted == False).outerjoin(
        Assignment, Task.assignment_id == Assignment.id
    )
    if current_user.role == "Employee":
        query = query.filter(_employee_task_filter(current_user)).distinct()
    if view == "active":
        query = query.filter(Task.is_active == True)
    elif view == "inactive":
        query = query.filter(Task.is_active == False)
    if status:
        query = query.filter(Task.status.in_(status))
    if priority:
        query = query.filter(Task.priority.in_(priority))
    if date_from:
        query = query.filter(Task.due_date >= date_from)
    if date_to:
        query = query.filter(Task.due_date <= date_to)
    row = query.with_entities(
        func.count(Task.id),
        func.coalesce(func.sum(case((Task.status == "Pending", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Task.status == "In Progress", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Task.status == "Completed", 1), else_=0)), 0),
        func.coalesce(func.sum(Task.estimated_hours), 0),
        func.coalesce(func.sum(Task.actual_hours), 0),
    ).first()
    if not row:
        return {"total": 0, "pending": 0, "in_progress": 0, "completed": 0, "estimated_hours": 0, "actual_hours": 0}
    return {
        "total": row[0] or 0,
        "pending": int(row[1] or 0),
        "in_progress": int(row[2] or 0),
        "completed": int(row[3] or 0),
        "estimated_hours": float(row[4] or 0),
        "actual_hours": float(row[5] or 0),
    }


@router.get("/by-lead/{lead_id}", response_model=List[LeadTaskOut])
def get_tasks_by_lead(lead_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Lead tasks (legacy): list tasks for a lead."""
    return db.query(LeadTask).filter(LeadTask.lead_id == lead_id, LeadTask.is_deleted == False).all()


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_out(task)


@router.post("", response_model=TaskOut, status_code=201)
def create_task(request: Request, data: TaskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Treat 0 as None for project_id to avoid FK constraint (no project with id=0)
    effective_client_id = data.client_id if (data.client_id is not None and data.client_id != 0) else None
    effective_project_id = data.project_id if (data.project_id is not None and data.project_id != 0) else None

    if not effective_client_id:
        raise HTTPException(status_code=400, detail="Client not found")
    client = db.query(Client).filter(Client.id == effective_client_id).first()
    if not client:
        raise HTTPException(status_code=400, detail="Client not found")
    assignment = db.query(Assignment).filter(Assignment.id == data.assignment_id, Assignment.is_deleted == False).first()
    if not assignment:
        raise HTTPException(status_code=400, detail="Assignment not found")
    if effective_project_id:
        project = db.query(Project).filter(Project.id == effective_project_id).first()
        if not project:
            raise HTTPException(status_code=400, detail="Project not found")

    task = Task(
        title=data.title,
        description=data.description,
        client_id=effective_client_id,
        project_id=effective_project_id,
        assignment_id=data.assignment_id,
        due_date=data.due_date,
        priority=data.priority or "Normal",
        estimated_hours=data.estimated_hours or 0,
        actual_hours=data.actual_hours or 0,
        brief_link=data.brief_link,
        resources_link=data.resources_link,
        client_folder_link=data.client_folder_link,
        work_link=data.work_link,
    )
    db.add(task)
    db.flush()
    # Support assigning by user list or by group (group takes precedence).
    assignee_ids = data.assignee_ids
    if data.assigned_to_group_id is None and (assignee_ids is None or assignee_ids == []):
        assignee_ids = [current_user.id]
    if data.assigned_to_group_id is not None:
        group = db.query(UserGroup).filter(UserGroup.id == data.assigned_to_group_id, UserGroup.is_deleted == False).first()
        if not group:
            raise HTTPException(status_code=400, detail="User group not found")
        task.assigned_users = [u for u in group.members if not getattr(u, "is_deleted", False)]
    elif assignee_ids is not None:
        if isinstance(assignee_ids, int):
            assignee_ids = [assignee_ids]
        assignee_ids = [x for x in assignee_ids if x is not None]
        users = db.query(User).filter(User.id.in_(assignee_ids)).all() if assignee_ids else []
        task.assigned_users = users
    db.commit()
    db.refresh(task)
    for user in task.assigned_users or []:
        create_notification(
            db,
            user.id,
            f"New task assigned: {task.title}",
            notif_type="task",
            target_url=f"/tasks/{task.id}",
            entity_id=task.id,
        )
    set_activity_description(request, describe_created("task", f"#{task.id}", task.title))
    return _task_to_out(task)


@router.put("/{task_id}", response_model=TaskOut)
def update_task(
    request: Request,
    task_id: int,
    data: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    old_assigned_ids = {u.id for u in task.assigned_users}
    u = data.model_dump(exclude_unset=True)
    assignee_ids = u.pop("assignee_ids", None)
    assigned_to_group_id = u.pop("assigned_to_group_id", None)
    # Treat 0 as None for project_id to avoid FK constraint
    if "project_id" in u and u["project_id"] == 0:
        u["project_id"] = None
    if "client_id" in u and u["client_id"] == 0:
        raise HTTPException(status_code=400, detail="Client not found")
    if "client_id" in u and u["client_id"] and not db.query(Client).filter(Client.id == u["client_id"]).first():
        raise HTTPException(status_code=400, detail="Client not found")
    if "project_id" in u and u["project_id"] and not db.query(Project).filter(Project.id == u["project_id"]).first():
        raise HTTPException(status_code=400, detail="Project not found")
    for k, v in u.items():
        setattr(task, k, v)
    # Multiple assignees: assignee_ids can be list [1,2,3] or single id; empty list clears assignees.
    # Group assignment takes precedence when provided.
    if assigned_to_group_id is not None:
        group = db.query(UserGroup).filter(UserGroup.id == assigned_to_group_id, UserGroup.is_deleted == False).first()
        if not group:
            raise HTTPException(status_code=400, detail="User group not found")
        task.assigned_users = [u for u in group.members if not getattr(u, "is_deleted", False)]
    elif assignee_ids is not None:
        if isinstance(assignee_ids, int):
            assignee_ids = [assignee_ids]
        assignee_ids = [x for x in assignee_ids if x is not None]
        task.assigned_users = db.query(User).filter(User.id.in_(assignee_ids)).all() if assignee_ids else []
    db.commit()
    db.refresh(task)
    if assignee_ids is not None or assigned_to_group_id is not None:
        new_assigned_ids = {u.id for u in task.assigned_users}
        newly_assigned = new_assigned_ids - old_assigned_ids
        for user in task.assigned_users or []:
            if user.id in newly_assigned:
                create_notification(
                    db,
                    user.id,
                    f"You were assigned a task: {task.title}",
                    notif_type="task",
                    target_url=f"/tasks/{task.id}",
                    entity_id=task.id,
                )
    changed = ", ".join(k for k in u.keys() if k != "assignee_ids") or "details"
    set_activity_description(request, describe_updated("task", f"#{task_id}", changed))
    return _task_to_out(task)


@router.delete("/{task_id}", status_code=204)
def delete_task(
    request: Request,
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    title = task.title
    task.is_deleted = True
    task.deleted_at = ist_now()
    db.commit()
    set_activity_description(request, describe_deleted("task", f"#{task_id}", title))
    return None


@router.delete("/{task_id}/hard-delete", status_code=204)
def hard_delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return None


# ----- Lead tasks (create/update/delete for lead context) -----
@router.post("/create", response_model=LeadTaskOut)
def create_lead_task(
    data: LeadTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = LeadTask(**data.model_dump(), created_by=current_user.username)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.put("/update/{task_id}", response_model=LeadTaskOut)
def update_lead_task(
    task_id: int,
    data: LeadTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(LeadTask).filter(LeadTask.id == task_id, LeadTask.is_deleted == False).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(task, key, value)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/delete/{task_id}")
def delete_lead_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(LeadTask).filter(LeadTask.id == task_id, LeadTask.is_deleted == False).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.is_deleted = True
    task.deleted_at = ist_now()
    db.commit()
    return {"detail": "Deleted"}


@router.delete("/delete/{task_id}/hard-delete")
def hard_delete_lead_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    task = db.query(LeadTask).filter(LeadTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"detail": "Permanently deleted"}
