from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from sqlalchemy.orm import Session
from utils.activity import set_activity_description, describe_created, describe_updated, describe_deleted
from database import get_db
from routers.auth import get_current_user, get_admin_user
from models.AssignmentModel import Assignment
from models.ClientModel import Client
from models.ProjectModel import Project
from models.UserGroupModel import UserGroup
from datetime import datetime, date
from utils.datetime_utils import ist_now
from models.UsersModel import User
from sqlalchemy import and_, or_, asc, desc
from typing import Optional, List
from sqlalchemy.orm import aliased
from pydantic import BaseModel
from utils.notifications import create_notification

router = APIRouter(prefix="/assignments", tags=["Assignments"])


class AssignmentCreate(BaseModel):
    assignment_code: Optional[str] = None  # e.g. ASG-001 or WEBSITE-REDESIGN (unique)
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    assigned_to: Optional[List[int]] = None  # User IDs; ignored if assigned_to_group_id is set
    assigned_to_group_id: Optional[int] = None  # When set, all group members are assigned and group name is stored
    priority: str
    client_id: Optional[int] = None  # Client (required in UI)
    project_id: Optional[int] = None  # Project (required in UI)
    estimated_hours: Optional[float] = 0
    actual_hours: Optional[float] = 0
    brief_link: Optional[str] = None
    resources_link: Optional[str] = None
    client_folder_link: Optional[str] = None
    work_link: Optional[str] = None


class AssignmentUpdate(BaseModel):
    assignment_code: Optional[str] = None
    title: str
    description: Optional[str] = None
    priority: str
    due_date: Optional[str] = None
    status: str
    client_id: Optional[int] = None
    project_id: Optional[int] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    brief_link: Optional[str] = None
    resources_link: Optional[str] = None
    client_folder_link: Optional[str] = None
    work_link: Optional[str] = None
    assigned_to: Optional[List[int]] = None  # List of user IDs to assign (replaces current assignees when provided)
    assigned_to_group_id: Optional[int] = None  # When set, all group members are assigned and group name is stored


class AssignmentStatusUpdate(BaseModel):
    status: str


class AssignmentPriorityUpdate(BaseModel):
    priority: str


def fix_old_self_assigned_assignments(db: Session, current_user: User):
    assignments = db.query(Assignment).filter(Assignment.created_by == current_user.username, Assignment.is_deleted == False).all()
    updated = 0
    for assignment in assignments:
        if current_user not in assignment.assigned_users:
            assignment.assigned_users.append(current_user)
            updated += 1
        if assignment.assigned_users and not assignment.assigned_to:
            assignment.assigned_to = ", ".join(
                _user_display_name(u) or u.username for u in assignment.assigned_users
            )
    db.commit()
    print(f"{updated} assignments fixed by assigning to self.")


def _employee_assignment_filter(current_user: User):
    return or_(
        Assignment.created_by == current_user.username,
        Assignment.assigned_by == current_user.username,
        Assignment.assigned_users.any(User.id == current_user.id),
    )


def _visible_assignment_filter():
    return or_(
        Assignment.created_by == "admin",
        Assignment.assigned_to.isnot(None),
        Assignment.assigned_users.any(),
    )


def _apply_assignment_assignee_filter(query, db: Session, assigned_to: str):
    assigned_user = db.query(User).filter(User.username == assigned_to).first()
    if not assigned_user and str(assigned_to).isdigit():
        assigned_user = db.query(User).filter(User.id == int(assigned_to)).first()
    if assigned_user:
        return query.join(Assignment.assigned_users).filter(User.id == assigned_user.id).distinct()
    return query.filter(Assignment.assigned_to.ilike(f"%{assigned_to}%"))


def _user_display_name(user: Optional[User]) -> str:
    """Return display name (first_name last_name) or username."""
    if not user:
        return ""
    return f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username


# List assignments (admin view)
@router.get("/list")
def list_assignments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: str = Query(""),
    priority: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    client_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    sort_by: str = Query("id"),
    order: str = Query("desc"),
    show_completed: bool = False,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    query = db.query(Assignment).filter(Assignment.is_deleted == False)
    if current_user.role == "Employee":
        fix_old_self_assigned_assignments(db, current_user)
        query = query.filter(_employee_assignment_filter(current_user)).distinct()
    else:
        query = query.filter(_visible_assignment_filter())

    if search:
        query = query.filter(or_(Assignment.title.ilike(f"%{search}%"), Assignment.assignment_code.ilike(f"%{search}%")))
    if priority:
        query = query.filter(Assignment.priority == priority)
    if status:
        query = query.filter(Assignment.status == status)
    if assigned_to:
        query = _apply_assignment_assignee_filter(query, db, assigned_to)
    if client_id:
        query = query.filter(Assignment.client_id == client_id)
    if project_id is not None:
        query = query.filter(Assignment.project_id == project_id)
    if not show_completed:
        query = query.filter(Assignment.status != "Completed")

    if start_date and end_date:
        query = query.filter(Assignment.created_at.between(start_date, end_date))

    sort_column = getattr(Assignment, sort_by, Assignment.id)
    if order == "asc":
        query = query.order_by(asc(sort_column))
    else:
        query = query.order_by(desc(sort_column))

    assignments_list = query.all()
    users = db.query(User).filter(User.role == "Employee").all()
    clients = db.query(Client).all()
    projects = db.query(Project).all()
    updater_usernames = list({t.updated_by for t in assignments_list if t.updated_by})
    updater_users = db.query(User).filter(User.username.in_(updater_usernames)).all() if updater_usernames else []
    updated_by_names = {u.username: _user_display_name(u) for u in updater_users}

    def _assignment_row(a):
        assigned_display = ", ".join(_user_display_name(u) or u.username for u in a.assigned_users) if a.assigned_users else (a.assigned_to or "")
        return {
            "id": a.id,
            "assignment_code": getattr(a, "assignment_code", None) or f"#{a.id}",
            "title": a.title,
            "description": a.description,
            "status": a.status,
            "priority": a.priority,
            "due_date": a.due_date.isoformat() if a.due_date else None,
            "created_by": a.created_by,
            "assigned_to": a.assigned_to,
            "assigned_to_display": assigned_display,
            "assigned_by": a.assigned_by,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "completed_at": a.completed_at.isoformat() if hasattr(a.completed_at, "isoformat") else a.completed_at,
            "client_id": a.client_id,
            "client_name": a.client.client_name if a.client else None,
            "project_id": getattr(a, "project_id", None),
            "project_name": a.project.project_name if getattr(a, "project", None) and a.project else None,
            "project_code": a.project.project_code if getattr(a, "project", None) and a.project else None,
            "estimated_hours": getattr(a, "estimated_hours", 0) or 0,
            "actual_hours": getattr(a, "actual_hours", 0) or 0,
            "brief_link": a.brief_link,
            "resources_link": a.resources_link,
            "client_folder_link": a.client_folder_link,
            "work_link": a.work_link,
            "updated_by": a.updated_by,
            "updated_by_name": updated_by_names.get(a.updated_by, "") if a.updated_by else "",
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            "assigned_users": [
                {"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name}
                for u in a.assigned_users
            ],
            "assigned_group_id": getattr(a, "assigned_group_id", None),
            "assigned_group_name": getattr(a, "assigned_group_name", None),
        }

    return {
        "assignments": [_assignment_row(a) for a in assignments_list],
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        },
        "filters": {
            "search": search,
            "priority": priority,
            "status": status,
            "assigned_to": assigned_to,
            "project_id": project_id,
            "sort_by": sort_by,
            "order": order
        },
        "users": [{"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name} for u in users],
        "clients": [{"id": c.id, "client_name": c.client_name} for c in clients],
        "projects": [{"id": p.id, "project_code": p.project_code, "project_name": p.project_name} for p in projects],
    }


# Admin: View all assignments (paginated)
@router.get("/admin-list")
def admin_list_assignments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    client_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    assigned_to_id: Optional[int] = Query(None),
    sort_by: str = Query("due_date"),
    order: str = Query("asc"),
    show_completed: bool = True,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """Admin-only route to view all work assignments with filters and pagination."""
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")

    query = db.query(Assignment)

    if search:
        query = query.filter(or_(Assignment.title.ilike(f"%{search}%"), Assignment.assignment_code.ilike(f"%{search}%")))
    if priority:
        query = query.filter(Assignment.priority == priority)
    if status:
        query = query.filter(Assignment.status == status)
    if client_id:
        query = query.filter(Assignment.client_id == client_id)
    if project_id is not None:
        query = query.filter(Assignment.project_id == project_id)
    if assigned_to_id:
        query = query.join(Assignment.assigned_users).filter(User.id == assigned_to_id).distinct()
    if not show_completed:
        query = query.filter(Assignment.status != "Completed")

    sort_column = getattr(Assignment, sort_by, Assignment.due_date)
    if order == "asc":
        query = query.order_by(asc(sort_column))
    else:
        query = query.order_by(desc(sort_column))

    total = query.count()
    assignments = query.offset(skip).limit(limit).all()

    users = db.query(User).filter(User.role == "Employee").all()
    clients = db.query(Client).all()
    projects = db.query(Project).all()
    updater_usernames = list({t.updated_by for t in assignments if t.updated_by})
    updater_users = db.query(User).filter(User.username.in_(updater_usernames)).all() if updater_usernames else []
    updated_by_names = {u.username: _user_display_name(u) for u in updater_users}

    def _row(t):
        assigned_display = ", ".join(_user_display_name(u) or u.username for u in t.assigned_users) if t.assigned_users else (t.assigned_to or "")
        return {
            "id": t.id,
            "assignment_code": getattr(t, "assignment_code", None) or f"#{t.id}",
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "priority": t.priority,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "created_by": t.created_by,
            "assigned_by": t.assigned_by,
            "assigned_to_display": assigned_display,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "completed_at": t.completed_at.isoformat() if hasattr(t.completed_at, "isoformat") and t.completed_at else t.completed_at,
            "client_id": t.client_id,
            "client_name": t.client.client_name if t.client else None,
            "project_id": getattr(t, "project_id", None),
            "project_name": t.project.project_name if getattr(t, "project", None) and t.project else None,
            "project_code": t.project.project_code if getattr(t, "project", None) and t.project else None,
            "estimated_hours": getattr(t, "estimated_hours", 0) or 0,
            "actual_hours": getattr(t, "actual_hours", 0) or 0,
            "brief_link": t.brief_link,
            "resources_link": t.resources_link,
            "client_folder_link": t.client_folder_link,
            "work_link": t.work_link,
            "updated_by": t.updated_by,
            "updated_by_name": updated_by_names.get(t.updated_by, "") if t.updated_by else "",
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            "assigned_users": [{"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name} for u in t.assigned_users],
            "assigned_group_id": getattr(t, "assigned_group_id", None),
            "assigned_group_name": getattr(t, "assigned_group_name", None),
        }

    return {
        "assignments": [_row(t) for t in assignments],
        "total": total,
        "skip": skip,
        "limit": limit,
        "users": [{"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name} for u in users],
        "clients": [{"id": c.id, "client_name": c.client_name} for c in clients],
        "projects": [{"id": p.id, "project_code": p.project_code, "project_name": p.project_name} for p in projects],
    }


# Employee assignments (drag and drop view)
@router.get("/employee-list")
def employee_assignments(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    show_completed: bool = False
):
    if current_user.role != "Employee":
        raise HTTPException(status_code=403, detail="Access denied")

    fix_old_self_assigned_assignments(db, current_user)

    query = db.query(Assignment).filter(
        Assignment.is_deleted == False,
        _employee_assignment_filter(current_user),
    ).distinct()

    if not show_completed:
        query = query.filter(Assignment.status != "Completed")

    assignments_list = query.order_by(Assignment.status.asc(), Assignment.created_at.desc()).all()

    users = db.query(User).filter(
        User.role == "Employee",
        User.username != current_user.username
    ).all()
    updater_usernames = list({t.updated_by for t in assignments_list if t.updated_by})
    updater_users = db.query(User).filter(User.username.in_(updater_usernames)).all() if updater_usernames else []
    updated_by_names = {u.username: _user_display_name(u) for u in updater_users}

    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        },
        "assignments": [
            {
                "id": a.id,
                "assignment_code": getattr(a, "assignment_code", None) or f"#{a.id}",
                "title": a.title,
                "description": a.description,
                "status": a.status,
                "priority": a.priority,
                "due_date": a.due_date.isoformat() if a.due_date else None,
                "created_by": a.created_by,
                "assigned_to": a.assigned_to,
                "assigned_by": a.assigned_by,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "client_id": a.client_id,
                "client_name": a.client.client_name if a.client else None,
                "project_id": getattr(a, "project_id", None),
                "project_name": a.project.project_name if getattr(a, "project", None) and a.project else None,
                "estimated_hours": getattr(a, "estimated_hours", 0),
                "actual_hours": getattr(a, "actual_hours", 0),
                "brief_link": a.brief_link,
                "resources_link": a.resources_link,
                "client_folder_link": a.client_folder_link,
                "work_link": a.work_link,
                "updated_by": a.updated_by,
                "updated_by_name": updated_by_names.get(a.updated_by, "") if a.updated_by else "",
                "updated_at": a.updated_at.isoformat() if a.updated_at else None,
                "assigned_group_id": getattr(a, "assigned_group_id", None),
                "assigned_group_name": getattr(a, "assigned_group_name", None),
            }
            for a in assignments_list
        ],
        "users": [{"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name} for u in users],
        "show_completed": show_completed
    }


# Employee assignments list view
@router.get("/employee/list")
def employee_assignments_list(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: str = Query(""),
    priority: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    sort_by: str = Query("id"),
    order: str = Query("desc")
):
    if current_user.role != "Employee":
        raise HTTPException(status_code=403, detail="Access denied")

    fix_old_self_assigned_assignments(db, current_user)

    query = db.query(Assignment).filter(
        Assignment.is_deleted == False,
        _employee_assignment_filter(current_user),
    ).distinct()

    if search:
        query = query.filter(Assignment.title.ilike(f"%{search}%"))
    if priority:
        query = query.filter(Assignment.priority == priority)
    if status:
        query = query.filter(Assignment.status == status)

    sort_column = getattr(Assignment, sort_by, Assignment.id)
    query = query.order_by(asc(sort_column) if order == "asc" else desc(sort_column))

    users = db.query(User).filter(User.role == "Employee").all()
    assignments_list = query.all()
    updater_usernames = list({t.updated_by for t in assignments_list if t.updated_by})
    updater_users = db.query(User).filter(User.username.in_(updater_usernames)).all() if updater_usernames else []
    updated_by_names = {u.username: _user_display_name(u) for u in updater_users}

    return {
        "assignments": [
            {
                "id": a.id,
                "assignment_code": getattr(a, "assignment_code", None) or f"#{a.id}",
                "title": a.title,
                "description": a.description,
                "status": a.status,
                "priority": a.priority,
                "due_date": a.due_date.isoformat() if a.due_date else None,
                "created_by": a.created_by,
                "assigned_to": a.assigned_to,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "client_id": a.client_id,
                "client_name": a.client.client_name if a.client else None,
                "project_id": getattr(a, "project_id", None),
                "project_name": a.project.project_name if getattr(a, "project", None) and a.project else None,
                "estimated_hours": getattr(a, "estimated_hours", 0),
                "actual_hours": getattr(a, "actual_hours", 0),
                "brief_link": a.brief_link,
                "resources_link": a.resources_link,
                "client_folder_link": a.client_folder_link,
                "work_link": a.work_link,
                "updated_by": a.updated_by,
                "updated_by_name": updated_by_names.get(a.updated_by, "") if a.updated_by else "",
                "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            }
            for a in assignments_list
        ],
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        },
        "filters": {"search": search, "priority": priority, "status": status, "sort_by": sort_by, "order": order},
        "users": [{"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name} for u in users],
    }


# Create assignment
@router.post("/create")
def create_assignment(
    request: Request,
    data: AssignmentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    assigned_to = data.assigned_to
    assigned_group_id = None
    assigned_group_name = None
    if data.assigned_to_group_id:
        group = db.query(UserGroup).filter(UserGroup.id == data.assigned_to_group_id, UserGroup.is_deleted == False).first()
        if not group:
            raise HTTPException(status_code=400, detail="User group not found")
        member_ids = [u.id for u in group.members]
        users = db.query(User).filter(User.id.in_(member_ids), User.is_deleted == False).all() if member_ids else []
        assigned_to = [u.id for u in users]
        assigned_group_id = group.id
        assigned_group_name = group.name
    if not assigned_to:
        assigned_to = [current_user.id]

    # Treat 0 as None to avoid FK constraint (no client/project with id=0)
    effective_client_id = data.client_id if (data.client_id is not None and data.client_id != 0) else None
    effective_project_id = data.project_id if (data.project_id is not None and data.project_id != 0) else None

    client_name = None
    if effective_client_id:
        client = db.query(Client).filter(Client.id == effective_client_id).first()
        if not client:
            raise HTTPException(status_code=400, detail="Client not found")
        client_name = client.client_name
    if effective_project_id:
        project = db.query(Project).filter(Project.id == effective_project_id).first()
        if not project:
            raise HTTPException(status_code=400, detail="Project not found")

    assignment = Assignment(
        assignment_code=data.assignment_code or None,
        title=data.title,
        description=data.description,
        created_by=current_user.username,
        created_at=ist_now(),
        assigned_by=current_user.username if assigned_to else None,
        due_date=datetime.strptime(data.due_date, "%Y-%m-%d") if data.due_date else None,
        priority=data.priority,
        client_id=effective_client_id,
        project_id=effective_project_id,
        estimated_hours=float(data.estimated_hours or 0),
        actual_hours=float(data.actual_hours or 0),
        brief_link=data.brief_link,
        resources_link=data.resources_link,
        client_folder_link=data.client_folder_link,
        work_link=data.work_link,
        assigned_group_id=assigned_group_id,
        assigned_group_name=assigned_group_name,
    )

    users = db.query(User).filter(User.id.in_(assigned_to)).all()
    assignment.assigned_users.extend(users)
    assignment.assigned_to = ", ".join(_user_display_name(u) or u.username for u in users) if users else None

    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    # If no assignment_code was provided, set default ASG-{id}
    if not assignment.assignment_code:
        assignment.assignment_code = f"ASG-{assignment.id}"
        db.commit()
        db.refresh(assignment)

    project_name = assignment.project.project_name if assignment.project else None
    deadline_str = assignment.due_date.strftime("%Y-%m-%d") if assignment.due_date else "No deadline"
    for user in users:
        message = f"New assignment: {assignment.title}"
        if client_name:
            message += f" - Client: {client_name}"
        message += f" - Deadline: {deadline_str} - Priority: {assignment.priority}"
        create_notification(
            db,
            user.id,
            message,
            notif_type="assignment",
            target_url=f"/assignments/{assignment.id}/view",
            entity_id=assignment.id,
        )

    set_activity_description(request, describe_created("assignment", assignment.assignment_code or f"#{assignment.id}", assignment.title))
    return {
        "message": "Assignment created successfully",
        "assignment": {
            "id": assignment.id,
            "assignment_code": assignment.assignment_code or f"#{assignment.id}",
            "title": assignment.title,
            "description": assignment.description,
            "status": assignment.status,
            "priority": assignment.priority,
            "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
            "created_by": assignment.created_by,
            "client_id": assignment.client_id,
            "client_name": client_name,
            "project_id": assignment.project_id,
            "project_name": project_name,
            "estimated_hours": assignment.estimated_hours,
            "actual_hours": assignment.actual_hours,
            "brief_link": assignment.brief_link,
            "resources_link": assignment.resources_link,
            "client_folder_link": assignment.client_folder_link,
            "work_link": assignment.work_link,
            "assigned_users": [{"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name} for u in assignment.assigned_users],
            "assigned_group_id": assignment.assigned_group_id,
            "assigned_group_name": assignment.assigned_group_name,
            "updated_by": assignment.updated_by,
            "updated_at": assignment.updated_at.isoformat() if assignment.updated_at else None,
        },
    }


# Update assignment status
@router.post("/{assignment_id}/update-status")
def update_assignment_status(
    request: Request,
    assignment_id: int,
    data: AssignmentStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id, Assignment.is_deleted == False).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    old_status = assignment.status
    assignment.status = data.status
    db.commit()

    set_activity_description(request, describe_updated("assignment", assignment.assignment_code or f"#{assignment_id}", f"status → {data.status}"))
    client_name = assignment.client.client_name if assignment.client else None
    for user in assignment.assigned_users:
        message = f"Assignment updated: {assignment.title} - Status changed from {old_status} to {data.status}"
        if client_name:
            message += f" - Client: {client_name}"
        create_notification(
            db,
            user.id,
            message,
            notif_type="assignment",
            target_url=f"/assignments/{assignment.id}/view",
            entity_id=assignment.id,
        )

    return {"message": "Assignment status updated successfully", "assignment_id": assignment_id, "status": data.status}


# Update assignment priority
@router.post("/{assignment_id}/update-priority")
def update_assignment_priority(
    request: Request,
    assignment_id: int,
    data: AssignmentPriorityUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id, Assignment.is_deleted == False).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    old_priority = assignment.priority
    assignment.priority = data.priority
    db.commit()

    set_activity_description(request, describe_updated("assignment", assignment.assignment_code or f"#{assignment_id}", f"priority → {data.priority}"))
    client_name = assignment.client.client_name if assignment.client else None
    for user in assignment.assigned_users:
        message = f"Assignment updated: {assignment.title} - Priority changed to {data.priority}"
        if client_name:
            message += f" - Client: {client_name}"
        create_notification(
            db,
            user.id,
            message,
            notif_type="assignment",
            target_url=f"/assignments/{assignment.id}/view",
            entity_id=assignment.id,
        )

    return {"message": "Priority updated successfully", "assignment_id": assignment_id, "priority": data.priority}


# Edit assignment (creator, assigned employee, or admin can update)
@router.put("/{assignment_id}/edit")
def update_assignment(
    request: Request,
    assignment_id: int,
    data: AssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id, Assignment.is_deleted == False).first()

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    is_creator = assignment.created_by == current_user.username
    is_assigned = current_user in assignment.assigned_users
    is_admin = current_user.role == "Admin"

    if not (is_creator or is_assigned or is_admin):
        raise HTTPException(status_code=403, detail="Not authorized to update this assignment")

    old_status = assignment.status
    old_priority = assignment.priority
    old_due_date = assignment.due_date
    old_client_id = assignment.client_id
    old_assigned_ids = {u.id for u in assignment.assigned_users}

    if data.assignment_code is not None:
        assignment.assignment_code = data.assignment_code
    assignment.title = data.title
    assignment.description = data.description
    assignment.priority = data.priority
    assignment.status = data.status
    # Treat 0 as None to avoid FK constraint; only update when field was sent
    if data.client_id is not None:
        effective_client_id = data.client_id if data.client_id != 0 else None
        if effective_client_id and not db.query(Client).filter(Client.id == effective_client_id).first():
            raise HTTPException(status_code=400, detail="Client not found")
        assignment.client_id = effective_client_id
    if data.project_id is not None:
        effective_project_id = data.project_id if data.project_id != 0 else None
        if effective_project_id and not db.query(Project).filter(Project.id == effective_project_id).first():
            raise HTTPException(status_code=400, detail="Project not found")
        assignment.project_id = effective_project_id
    if data.estimated_hours is not None:
        assignment.estimated_hours = data.estimated_hours
    if data.actual_hours is not None:
        assignment.actual_hours = data.actual_hours
    assignment.brief_link = data.brief_link
    assignment.resources_link = data.resources_link
    assignment.client_folder_link = data.client_folder_link
    assignment.work_link = data.work_link
    assignment.updated_by = current_user.username
    assignment.updated_at = ist_now()

    if data.due_date:
        assignment.due_date = datetime.strptime(data.due_date, "%Y-%m-%d")

    if data.status == "Completed" and old_status != "Completed":
        assignment.completed_at = ist_now()
    elif data.status != "Completed" and old_status == "Completed":
        assignment.completed_at = None

    # Update assigned users: group takes precedence over individual list
    if data.assigned_to_group_id is not None:
        group = db.query(UserGroup).filter(UserGroup.id == data.assigned_to_group_id, UserGroup.is_deleted == False).first()
        if not group:
            raise HTTPException(status_code=400, detail="User group not found")
        member_ids = [u.id for u in group.members]
        users = db.query(User).filter(User.id.in_(member_ids), User.is_deleted == False).all() if member_ids else []
        assignment.assigned_users = users
        assignment.assigned_to = ", ".join(_user_display_name(u) or u.username for u in users) if users else None
        assignment.assigned_group_id = group.id
        assignment.assigned_group_name = group.name
    elif data.assigned_to is not None:
        assigned_to_ids = [x for x in data.assigned_to if x is not None]
        users = db.query(User).filter(User.id.in_(assigned_to_ids), User.is_deleted == False).all() if assigned_to_ids else []
        if assigned_to_ids and len(users) != len(assigned_to_ids):
            found_ids = {u.id for u in users}
            missing = [i for i in assigned_to_ids if i not in found_ids]
            raise HTTPException(status_code=400, detail=f"User(s) not found: {missing}")
        assignment.assigned_users = users
        assignment.assigned_to = ", ".join(_user_display_name(u) or u.username for u in users) if users else None
        assignment.assigned_group_id = None
        assignment.assigned_group_name = None

    db.commit()
    db.refresh(assignment)

    client_name = assignment.client.client_name if assignment.client else None
    deadline_str = assignment.due_date.strftime("%Y-%m-%d") if assignment.due_date else "No deadline"

    if old_status != assignment.status:
        for user in assignment.assigned_users:
            message = f"Assignment updated: {assignment.title} - Status changed from {old_status} to {assignment.status}"
            if client_name:
                message += f" - Client: {client_name}"
            create_notification(
                db,
                user.id,
                message,
                notif_type="assignment",
                target_url=f"/assignments/{assignment.id}/view",
                entity_id=assignment.id,
            )

    if old_priority != assignment.priority:
        for user in assignment.assigned_users:
            message = f"Assignment updated: {assignment.title} - Priority changed to {assignment.priority}"
            if client_name:
                message += f" - Client: {client_name}"
            create_notification(
                db,
                user.id,
                message,
                notif_type="assignment",
                target_url=f"/assignments/{assignment.id}/view",
                entity_id=assignment.id,
            )

    if old_due_date != assignment.due_date:
        for user in assignment.assigned_users:
            message = f"Assignment updated: {assignment.title} - Deadline changed to {deadline_str}"
            if client_name:
                message += f" - Client: {client_name}"
            create_notification(
                db,
                user.id,
                message,
                notif_type="assignment",
                target_url=f"/assignments/{assignment.id}/view",
                entity_id=assignment.id,
            )

    if old_client_id != assignment.client_id:
        for user in assignment.assigned_users:
            message = f"Assignment updated: {assignment.title} - Client changed"
            if client_name:
                message += f" to {client_name}"
            create_notification(
                db,
                user.id,
                message,
                notif_type="assignment",
                target_url=f"/assignments/{assignment.id}/view",
                entity_id=assignment.id,
            )

    # Notify newly assigned users when assignees change
    if data.assigned_to is not None or data.assigned_to_group_id is not None:
        new_assigned_ids = {u.id for u in assignment.assigned_users}
        newly_assigned = new_assigned_ids - old_assigned_ids
        for user in assignment.assigned_users:
            if user.id in newly_assigned:
                message = f"You were assigned to: {assignment.title}"
                if client_name:
                    message += f" - Client: {client_name}"
                create_notification(
                    db,
                    user.id,
                    message,
                    notif_type="assignment",
                    target_url=f"/assignments/{assignment.id}/view",
                    entity_id=assignment.id,
                )

    changes = []
    if old_status != assignment.status:
        changes.append(f"status → {assignment.status}")
    if old_priority != assignment.priority:
        changes.append(f"priority → {assignment.priority}")
    if old_due_date != assignment.due_date:
        changes.append("due_date updated")
    if old_client_id != assignment.client_id:
        changes.append("client updated")
    if (data.assigned_to is not None or data.assigned_to_group_id is not None) and old_assigned_ids != {u.id for u in assignment.assigned_users}:
        changes.append("assigned_to updated")
    set_activity_description(request, describe_updated("assignment", assignment.assignment_code or f"#{assignment_id}", ", ".join(changes) if changes else "details"))

    updated_by_name = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.username

    return {
        "message": "Assignment updated successfully",
        "assignment": {
            "id": assignment.id,
            "assignment_code": getattr(assignment, "assignment_code", None) or f"#{assignment.id}",
            "title": assignment.title,
            "description": assignment.description,
            "status": assignment.status,
            "priority": assignment.priority,
            "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
            "client_id": assignment.client_id,
            "client_name": client_name,
            "project_id": getattr(assignment, "project_id", None),
            "project_name": assignment.project.project_name if getattr(assignment, "project", None) and assignment.project else None,
            "estimated_hours": getattr(assignment, "estimated_hours", 0),
            "actual_hours": getattr(assignment, "actual_hours", 0),
            "brief_link": assignment.brief_link,
            "resources_link": assignment.resources_link,
            "client_folder_link": assignment.client_folder_link,
            "work_link": assignment.work_link,
            "updated_by": assignment.updated_by,
            "updated_by_name": updated_by_name,
            "updated_at": assignment.updated_at.isoformat() if assignment.updated_at else None,
            "assigned_users": [
                {"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name}
                for u in assignment.assigned_users
            ],
            "assigned_group_id": getattr(assignment, "assigned_group_id", None),
            "assigned_group_name": getattr(assignment, "assigned_group_name", None),
        },
    }


# Get single assignment
@router.get("/{assignment_id}/view")
def get_assignment(assignment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id, Assignment.is_deleted == False).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    is_creator = assignment.created_by == current_user.username
    is_assigned = current_user in assignment.assigned_users
    is_admin = current_user.role == "Admin"

    if not (is_creator or is_assigned or is_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    updated_by_name = ""
    if assignment.updated_by:
        updater = db.query(User).filter(User.username == assignment.updated_by).first()
        updated_by_name = _user_display_name(updater)

    return {
        "id": assignment.id,
        "assignment_code": getattr(assignment, "assignment_code", None) or f"#{assignment.id}",
        "title": assignment.title,
        "description": assignment.description,
        "priority": assignment.priority,
        "due_date": str(assignment.due_date) if assignment.due_date else None,
        "status": assignment.status,
        "client_id": assignment.client_id,
        "client_name": assignment.client.client_name if assignment.client else None,
        "project_id": getattr(assignment, "project_id", None),
        "project_name": assignment.project.project_name if getattr(assignment, "project", None) and assignment.project else None,
        "project_code": assignment.project.project_code if getattr(assignment, "project", None) and assignment.project else None,
        "estimated_hours": getattr(assignment, "estimated_hours", 0),
        "actual_hours": getattr(assignment, "actual_hours", 0),
        "brief_link": assignment.brief_link,
        "resources_link": assignment.resources_link,
        "client_folder_link": assignment.client_folder_link,
        "work_link": assignment.work_link,
        "created_by": assignment.created_by,
        "assigned_by": assignment.assigned_by,
        "created_at": assignment.created_at.isoformat() if assignment.created_at else None,
        "completed_at": assignment.completed_at if assignment.completed_at else None,
        "updated_by": assignment.updated_by,
        "updated_by_name": updated_by_name,
        "updated_at": assignment.updated_at.isoformat() if assignment.updated_at else None,
        "assigned_users": [
            {"id": user.id, "username": user.username, "first_name": user.first_name, "last_name": user.last_name}
            for user in assignment.assigned_users
        ],
        "assigned_group_id": getattr(assignment, "assigned_group_id", None),
        "assigned_group_name": getattr(assignment, "assigned_group_name", None),
    }


# Delete assignment (soft delete; creator or admin)
@router.delete("/{assignment_id}/delete")
def delete_assignment(request: Request, assignment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id, Assignment.is_deleted == False).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    if assignment.created_by != current_user.username and current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Not authorized to delete this assignment")

    code = assignment.assignment_code or f"#{assignment_id}"
    title = assignment.title or ""
    assignment.is_deleted = True
    assignment.deleted_at = ist_now()
    db.commit()
    set_activity_description(request, describe_deleted("assignment", code, title))
    return {"message": "Assignment deleted successfully", "assignment_id": assignment_id}


# Hard delete assignment (Admin only; permanently removes record)
@router.delete("/{assignment_id}/hard-delete")
def hard_delete_assignment(
    request: Request,
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    code = assignment.assignment_code or f"#{assignment_id}"
    title = assignment.title or ""
    db.delete(assignment)
    db.commit()
    set_activity_description(request, describe_deleted("assignment (hard)", code, title))
    return {"message": "Assignment permanently deleted", "assignment_id": assignment_id}
