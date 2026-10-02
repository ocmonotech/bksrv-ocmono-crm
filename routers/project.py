from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from database import get_db
from models.ProjectModel import Project
from models.ClientModel import Client
from models.ProjectTypeModel import ProjectType
from models.UsersModel import User
from routers.auth import get_current_user, get_admin_user
from datetime import datetime, timedelta, date, timezone as dt_timezone
from utils.datetime_utils import ist_now, IST
from sqlalchemy import func, text, and_, or_, extract
from typing import Optional, List
from models.ProjectTimerModel import ProjectTimer
from models.AttendanceModel import Attendance
from collections import defaultdict
from models.ProjectSubtaskModel import ProjectSubtask, SubtaskLog, SubtaskAttachment, SubtaskComment
from dateutil import parser
from models.AssignmentModel import Assignment
from models.UserGroupModel import UserGroup
from pydantic import BaseModel
from dateutil import parser
from utils.notifications import create_notification

router = APIRouter(prefix="/project", tags=["Project"])


# Pydantic models
class ProjectCreate(BaseModel):
    project_code: str
    project_name: str
    client_id: int
    project_type: str
    assigned_persons: List[str]
    assigned_to_group_id: Optional[int] = None
    project_status: str
    project_note: str


class ProjectUpdate(BaseModel):
    project_name: str
    client_id: int
    project_type: str
    assigned_persons: List[str]
    assigned_to_group_id: Optional[int] = None
    project_status: str
    project_note: str


class ManualLogTime(BaseModel):
    log_date: str
    start_time: str
    end_time: str
    notes: Optional[str] = None


class EndTimerRequest(BaseModel):
    notes: Optional[str] = None


def format_time(val):
    if not val:
        return None
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val)
            return dt.strftime("%I:%M %p")
        except Exception:
            return val
    return val.strftime("%I:%M %p")


def get_datetime(val):
    if not val:
        return None
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val)
        except Exception:
            return None
    return val


def format_seconds(seconds):
    hours = int(seconds) // 3600
    minutes = (int(seconds) % 3600) // 60
    seconds = int(seconds) % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def seconds_to_hm(seconds):
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h:02d}h {m:02d}m"


def safe_format_date(value):
    try:
        dt = parser.parse(str(value))
        return dt.strftime("%d %b %Y")
    except Exception:
        return "N/A"


# Project Time Chart Data
@router.get("/chart/project-time-log-data")
def get_project_time_chart_data(view: str = 'week', db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    today = datetime.today()

    if view == 'month':
        start_date = today.replace(day=1)
        end_date = today
        labels = [(start_date + timedelta(days=i)).strftime("%d %b") for i in range((end_date - start_date).days + 1)]
    else:
        start_date = today - timedelta(days=today.weekday())
        labels = [(start_date + timedelta(days=i)).strftime("%a") for i in range(7)]

    date_index = {
        (start_date + timedelta(days=i)).date(): i for i in range(len(labels))
    }

    logs = db.query(ProjectTimer).filter(ProjectTimer.start_time >= start_date).all()

    project_time_data = {}
    for log in logs:
        if log.project_id not in project_time_data:
            project_time_data[log.project_id] = [0] * len(labels)

        log_date = log.start_time.date()
        if log_date in date_index and log.end_time:
            duration = int((log.end_time - log.start_time).total_seconds() // 60)
            project_time_data[log.project_id][date_index[log_date]] += duration

    return {
        "labels": labels,
        "datasets": [
            {"label": code, "data": data} for code, data in project_time_data.items()
        ]
    }


# Total project counts grouped by status
@router.get("/project-status-summary")
def get_project_status_summary(db: Session = Depends(get_db)):
    status_counts = (
        db.query(Project.project_status, func.count(Project.id))
        .group_by(Project.project_status)
        .all()
    )

    result = {
        "Active": 0,
        "Pending": 0,
        "Completed": 0
    }

    for status, count in status_counts:
        normalized_status = status.strip().lower()
        if normalized_status == "in progress":
            result["Active"] = count
        elif normalized_status == "not started":
            result["Pending"] = count
        elif normalized_status == "completed":
            result["Completed"] = count

    return result


# Employee Project Subtasks
@router.get("/employee-project-subtasks/{project_code}")
def employee_project_subtasks(project_code: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    project = db.query(Project).filter(Project.project_code == project_code).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    assigned_usernames = [p.strip().lower() for p in project.assigned_persons.split(",")]
    # if current_user.username.lower() not in assigned_usernames:
    #     raise HTTPException(status_code=403, detail="Access denied")

    subtasks = db.query(ProjectSubtask).filter(
        ProjectSubtask.project_id == project.id,
        ProjectSubtask.assigned_to == current_user.username
    ).all()

    subtask_ids = [s.id for s in subtasks]

    attachments = db.query(SubtaskAttachment).filter(SubtaskAttachment.subtask_id.in_(subtask_ids)).all()
    comments = db.query(SubtaskComment).filter(SubtaskComment.subtask_id.in_(subtask_ids)).all()

    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        },
        "project": {
            "id": project.id,
            "project_code": project.project_code,
            "project_name": project.project_name,
            "project_status": project.project_status,
            "project_client": project.project_client
        },
        "subtasks": [
            {
                "id": s.id,
                "title": s.title,
                "status": s.status,
                "assigned_to": s.assigned_to,
                "project_id": s.project_id
            }
            for s in subtasks
        ],
        "attachments": [
            {
                "id": a.id,
                "subtask_id": a.subtask_id,
                "filename": a.filename,
                "filepath": a.filepath,
                "uploaded_by": a.uploaded_by,
                "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None
            }
            for a in attachments
        ],
        "comments": [
            {
                "id": c.id,
                "subtask_id": c.subtask_id,
                "comment_text": c.comment_text,
                "created_by": c.created_by,
                "commented_at": c.commented_at.isoformat() if c.commented_at else None
            }
            for c in comments
        ]
    }


def parse_time(value):
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%H:%M:%S")
        except ValueError:
            return None
    return value


# Project Details
@router.get("/project-details/{project_code}")
def project_detail(
    project_code: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    project = db.query(Project).filter(Project.project_code == project_code).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    time_summary = {}
    date_summary = defaultdict(int)
    timers = db.query(ProjectTimer).filter(ProjectTimer.project_id == project.id).all()

    for timer in timers:
        username = timer.employee_username

        start_time = parse_time(timer.start_time)
        end_time = parse_time(timer.end_time) or ist_now()

        if start_time and end_time:
            duration = (end_time - start_time).total_seconds()
            time_summary[username] = time_summary.get(username, 0) + duration

            if timer.date:
                date_key = timer.date.strftime("%Y-%m-%d")
                date_summary[date_key] += duration

    readable_summary = {k: seconds_to_hm(v) for k, v in time_summary.items()}
    sorted_dates = sorted(date_summary.items())
    chart_labels = [d[0] for d in sorted_dates]
    chart_values = [round(d[1] / 60, 2) for d in sorted_dates]

    if current_user.role == "Employee":
        subtasks = db.query(ProjectSubtask).filter(
            ProjectSubtask.project_id == project.id,
            ProjectSubtask.assigned_to == current_user.username
        ).all()
    else:
        subtasks = db.query(ProjectSubtask).filter(ProjectSubtask.project_id == project.id).all()

    raw_assigned = project.assigned_persons or ""
    assigned_usernames = [u.strip() for u in raw_assigned.split(",") if u.strip()]

    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        },
        "project": {
            "id": project.id,
            "project_code": project.project_code,
            "project_name": project.project_name,
            "project_status": project.project_status,
            "project_type_name": project.project_type_name,
            "assigned_persons": project.assigned_persons,
            "project_note": project.project_note,
            "client_id": project.client_id,
            "project_client": project.project_client
        },
        "time_summary": readable_summary,
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "subtasks": [
            {
                "id": s.id,
                "title": s.title,
                "status": s.status,
                "assigned_to": s.assigned_to
            }
            for s in subtasks
        ],
        "assigned_usernames": assigned_usernames
    }


# Employee update status of projects
@router.post("/employee-update-status/{project_id}")
def employee_update_status(
    project_id: str,
    status_data: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "Employee":
        raise HTTPException(status_code=403, detail="Unauthorized access")

    project = db.query(Project).filter(Project.id == project_id, Project.is_deleted == False).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    assigned_names = [name.strip() for name in project.assigned_persons.split(",")]
    if current_user.first_name not in assigned_names:
        raise HTTPException(status_code=403, detail="Not authorized to update this project")

    status = status_data.get("status")
    if status not in ["Completed","In Progress","Not Started"]:
        raise HTTPException(status_code=400, detail="Invalid status update")

    project.project_status = status
    db.commit()
    
    return {"message": "Project status updated successfully", "project_id": project_id, "status": status}


# Timer summary
@router.get("/project-timer-summary")
def project_timer_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    range: str = Query("today", regex="^(today|yesterday|this_week|last_7_days|last_week|last_14_days|this_month|last_month)$"),
    filter_by: Optional[str] = Query(""),
    filter_value: Optional[str] = Query("")
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access denied")

    today = ist_now().date()

    if range == "today":
        start = end = today
    elif range == "yesterday":
        start = end = today - timedelta(days=1)
    elif range == "this_week":
        start = today - timedelta(days=today.weekday())
        end = today
    elif range == "last_7_days":
        start = today - timedelta(days=6)
        end = today
    elif range == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
    elif range == "last_14_days":
        start = today - timedelta(days=13)
        end = today
    elif range == "this_month":
        start = today.replace(day=1)
        end = today
    elif range == "last_month":
        first_day = today.replace(day=1)
        end = first_day - timedelta(days=1)
        start = end.replace(day=1)

    timer_summary = []
    projects = db.query(Project).all()

    for project in projects:
        total_project_secs = 0
        assigned_display = []

        usernames = db.query(ProjectTimer.employee_username).filter(
            ProjectTimer.project_id == project.id,
            ProjectTimer.date >= start,
            ProjectTimer.date <= end
        ).distinct().all()

        for (username,) in usernames:
            timers = db.query(ProjectTimer).filter(
                ProjectTimer.project_id == project.id,
                ProjectTimer.employee_username == username,
                ProjectTimer.date >= start,
                ProjectTimer.date <= end
            ).all()

            person_total_secs = sum(
                (
                    (parser.parse(t.end_time) if t.end_time else ist_now()) -
                    parser.parse(t.start_time)
                ).total_seconds()
                for t in timers
            )

            if person_total_secs > 0:
                total_project_secs += person_total_secs
                assigned_display.append(f"{username} ({seconds_to_hm(person_total_secs)})")

        if total_project_secs > 0:
            timer_summary.append({
                "project_code": project.project_code or "N/A",
                "project_name": project.project_name or "N/A",
                "project_type": project.project_type_name or "N/A",
                "assigned_to": assigned_display,
                "project_status": project.project_status or "N/A",
                "total_time": seconds_to_hm(total_project_secs)
            })

    if filter_by and filter_value:
        def match(project, field, value):
            if field == "assigned_to":
                return any(value.lower() in name.lower() for name in project["assigned_to"])
            return value.lower() in str(project.get(field, "")).lower()

        timer_summary = [p for p in timer_summary if match(p, filter_by, filter_value)]

    return {
        "projects": timer_summary,
        "selected_range": range,
        "filter_by": filter_by,
        "filter_value": filter_value,
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        }
    }


# Get project for editing
@router.get("/edit-project/{project_id}")
def edit_project_form(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    project = db.query(Project).filter(Project.id == project_id, Project.is_deleted == False).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    clients = db.query(Client).filter(Client.is_deleted == False).all()
    project_types = db.query(ProjectType).all()
    employees = db.query(User).all()

    return {
        "project": {
            "id": project.id,
            "project_code": project.project_code,
            "project_name": project.project_name,
            "client_id": project.client_id,
            "project_type_name": project.project_type_name,
            "assigned_persons": project.assigned_persons,
            "project_status": project.project_status,
            "project_note": project.project_note
        },
        "clients": [{"id": c.id, "client_name": c.client_name} for c in clients],
        "project_types": [{"id": pt.id, "type_name": pt.type_name} for pt in project_types],
        "employees": [
            {
                "id": e.id,
                "username": e.username,
                "first_name": e.first_name,
                "last_name": e.last_name
            }
            for e in employees
        ],
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        }
    }


# Update project
@router.put("/edit-project/{project_id}")
def update_project(
    project_id: int,
    project_data: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    project = db.query(Project).filter(Project.id == project_id, Project.is_deleted == False).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    old_first_names = {n.strip() for n in (project.assigned_persons or "").split(",") if n.strip()}

    assigned_usernames = list(project_data.assigned_persons or [])
    if project_data.assigned_to_group_id:
        group = db.query(UserGroup).filter(UserGroup.id == project_data.assigned_to_group_id, UserGroup.is_deleted == False).first()
        if not group:
            raise HTTPException(status_code=400, detail="User group not found")
        assigned_usernames.extend([u.username for u in group.members if u.username])
    assigned_usernames = list(dict.fromkeys([u for u in assigned_usernames if u]))

    first_names = []
    for username in assigned_usernames:
        user = db.query(User).filter(User.username == username).first()
        if user:
            first_names.append(user.first_name)

    client = db.query(Client).filter(Client.id == project_data.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    project.project_name = project_data.project_name
    project.client_id = project_data.client_id
    project.project_client = client.client_name
    project.project_type_name = project_data.project_type
    project.assigned_persons = ", ".join(first_names)
    project.project_status = project_data.project_status
    project.project_note = project_data.project_note

    db.commit()
    db.refresh(project)
    new_assignees = [u for u in db.query(User).filter(User.username.in_(assigned_usernames)).all()]
    for u in new_assignees:
        if (u.first_name or "").strip() not in old_first_names:
            create_notification(
                db,
                u.id,
                f"You were assigned to project: {project.project_name}",
                notif_type="project",
                target_url=f"/project/project-details/{project.project_code}",
                entity_id=project.id,
            )
    
    return {
        "message": "Project updated successfully",
        "project": {
            "id": project.id,
            "project_code": project.project_code,
            "project_name": project.project_name,
            "project_status": project.project_status
        }
    }


# Admin view of all timer logs
@router.get("/all-timer-logs")
async def all_timer_logs(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    projects = db.query(Project).all()

    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        },
        "projects": [
            {
                "id": p.id,
                "project_code": p.project_code,
                "project_name": p.project_name,
                "project_status": p.project_status,
                "total_time_spent": p.total_time_spent or 0,
                "formatted_time": format_seconds(p.total_time_spent or 0)
            }
            for p in projects
        ]
    }


# Admin Dashboard
@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    total_projects = db.query(Project).count()
    total_clients = db.query(Client).count()
    total_employees = db.query(User).filter(User.role == "Employee").count()

    in_progress_count = db.query(Project).filter(Project.is_deleted == False, Project.project_status == "In Progress").count()
    completed_count = db.query(Project).filter(Project.is_deleted == False, Project.project_status == "Completed").count()
    not_started_count = db.query(Project).filter(Project.is_deleted == False, Project.project_status == "Not Started").count()

    recent_projects = db.query(Project).order_by(Project.id.desc()).limit(5).all()

    raw_clients = db.query(Project.project_client).distinct().all()

    client_list = []
    for (client_name,) in raw_clients:
        if client_name:
            client_list.append({
                "name": client_name,
                "country": "India",
                "role": "Client of EMS",
                "avatar": "assets/images/users/avatar-1.jpg"
            })

    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        },
        "total_projects": total_projects,
        "total_clients": total_clients,
        "total_employees": total_employees,
        "in_progress_count": in_progress_count,
        "completed_count": completed_count,
        "not_started_count": not_started_count,
        "recent_projects": [
            {
                "id": p.id,
                "project_code": p.project_code,
                "project_name": p.project_name,
                "project_status": p.project_status,
                "project_client": p.project_client
            }
            for p in recent_projects
        ],
        "clients": client_list
    }


# Get data for adding project
@router.get("/add-project")
def add_project_form(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    clients = db.query(Client).all()
    project_types = db.query(ProjectType).all()
    employees = db.query(User).all()

    now = ist_now()
    project_code = now.strftime("%d%m%y-%H%M%S")

    return {
        "clients": [{"id": c.id, "client_name": c.client_name} for c in clients],
        "project_types": [{"id": pt.id, "type_name": pt.type_name} for pt in project_types],
        "employees": [
            {
                "id": e.id,
                "username": e.username,
                "first_name": e.first_name,
                "last_name": e.last_name
            }
            for e in employees
        ],
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        },
        "project_code": project_code
    }


# Add Project
@router.post("/add-project")
def add_project(
    project_data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    client = db.query(Client).filter(Client.id == project_data.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    assigned_usernames = list(project_data.assigned_persons or [])
    if project_data.assigned_to_group_id:
        group = db.query(UserGroup).filter(UserGroup.id == project_data.assigned_to_group_id, UserGroup.is_deleted == False).first()
        if not group:
            raise HTTPException(status_code=400, detail="User group not found")
        assigned_usernames.extend([u.username for u in group.members if u.username])
    assigned_usernames = list(dict.fromkeys([u for u in assigned_usernames if u]))

    first_names = []
    for username in assigned_usernames:
        user = db.query(User).filter(User.username == username).first()
        if user:
            first_names.append(user.first_name)

    project = Project(
        project_code=project_data.project_code,
        project_name=project_data.project_name,
        client_id=project_data.client_id,
        project_client=client.client_name,
        project_type_name=project_data.project_type,
        assigned_persons=", ".join(first_names),
        project_status=project_data.project_status,
        project_note=project_data.project_note,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    assignees = db.query(User).filter(User.username.in_(assigned_usernames)).all()
    for u in assignees:
        create_notification(
            db,
            u.id,
            f"New project assigned: {project.project_name}",
            notif_type="project",
            target_url=f"/project/project-details/{project.project_code}",
            entity_id=project.id,
        )

    return {
        "message": "Project added successfully",
        "project": {
            "id": project.id,
            "project_code": project.project_code,
            "project_name": project.project_name,
            "project_status": project.project_status
        }
    }


# Delete Project (soft delete)
@router.delete("/delete-project/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    project = db.query(Project).filter(Project.id == project_id, Project.is_deleted == False).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.is_deleted = True
    project.deleted_at = ist_now()
    db.commit()
    return {"message": "Project deleted successfully", "project_id": project_id}


# Hard delete Project (Admin only)
@router.delete("/delete-project/{project_id}/hard-delete")
def hard_delete_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()
    return {"message": "Project permanently deleted", "project_id": project_id}


# All Projects Route (with client_id filter and client info)
@router.get("/all-projects")
def all_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    filter_by: Optional[str] = Query(None),
    filter_value: Optional[str] = Query(None),
    client_id: Optional[int] = Query(None),
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    query = db.query(Project).filter(Project.is_deleted == False)

    if client_id is not None:
        query = query.filter(Project.client_id == client_id)

    if filter_by and filter_value:
        filter_value_lower = filter_value.lower()
        if filter_by == "project_status":
            query = query.filter(Project.project_status.ilike(f"%{filter_value}%"))
        elif filter_by == "project_type_name":
            query = query.filter(Project.project_type_name.ilike(f"%{filter_value}%"))
        elif filter_by == "project_code":
            query = query.filter(Project.project_code.ilike(f"%{filter_value}%"))
        elif filter_by == "project_name":
            query = query.filter(Project.project_name.ilike(f"%{filter_value}%"))
        elif filter_by == "project_client":
            query = query.filter(Project.project_client.ilike(f"%{filter_value}%"))
        elif filter_by == "assigned_persons":
            query = query.filter(Project.assigned_persons.ilike(f"%{filter_value}%"))

    projects = query.all()
    project_types = db.query(ProjectType).all()
    clients = db.query(Client).all()

    return {
        "projects": [
            {
                "id": p.id,
                "project_code": p.project_code,
                "project_name": p.project_name,
                "project_status": p.project_status,
                "project_type_name": p.project_type_name,
                "project_client": p.project_client,
                "client_id": p.client_id,
                "client_name": p.client.client_name if p.client else p.project_client,
                "assigned_persons": p.assigned_persons,
                "project_note": p.project_note
            }
            for p in projects
        ],
        "project_types": [{"id": pt.id, "type_name": pt.type_name} for pt in project_types],
        "clients": [{"id": c.id, "client_name": c.client_name} for c in clients],
        "filter_by": filter_by,
        "filter_value": filter_value,
        "client_id": client_id,
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        }
    }


# Employee Dashboard
@router.get("/employee-dashboard")
def employee_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != "Employee":
        raise HTTPException(status_code=403, detail="Access forbidden")

    username = current_user.username

    my_assignments_query = db.query(Assignment).filter(
        Assignment.is_deleted == False,
        or_(
            Assignment.created_by == username,
            Assignment.assigned_by == username,
            Assignment.assigned_users.any(User.id == current_user.id),
        ),
    ).distinct()
    total_tasks = my_assignments_query.count()
    assigned_projects = db.query(Project).filter(Project.assigned_persons.like(f"%{current_user.first_name}%")).count()
    completed_tasks = db.query(Project).filter(Project.assigned_persons == username, Project.project_status == "Completed").count()
    recent_activities = db.query(Project).filter(Project.assigned_persons == username).order_by(Project.id.desc()).limit(5).all()

    timers = db.query(ProjectTimer).filter(ProjectTimer.employee_username == username).all()
    total_seconds = 0
    for t in timers:
        start = t.start_time
        end = t.end_time
        if not start or not end:
            continue
        if isinstance(start, str):
            start = datetime.fromisoformat(start)
        if isinstance(end, str):
            end = datetime.fromisoformat(end)
        total_seconds += (end - start).total_seconds()

    hours_logged = round(total_seconds / 3600, 2)

    today_attendance = db.query(Attendance).filter(
        and_(
            Attendance.username == username,
            Attendance.date == ist_now().date()
        )
    ).first()

    login_time = today_attendance.login_time.strftime("%I:%M %p") if today_attendance and today_attendance.login_time else "N/A"
    logout_time = today_attendance.logout_time.strftime("%I:%M %p") if today_attendance and today_attendance.logout_time else "N/A"

    my_tasks = my_assignments_query.all()
    task_rows = [{
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "due_date": safe_format_date(t.due_date),
        "status_class": "success" if t.status == "Completed" else "warning" if t.status == "In Progress" else "secondary"
    } for t in my_tasks]

    daily_logs = defaultdict(int)
    for t in timers:
        if t.start_time and t.end_time:
            try:
                start = datetime.fromisoformat(str(t.start_time)) if isinstance(t.start_time, str) else t.start_time
                end = datetime.fromisoformat(str(t.end_time)) if isinstance(t.end_time, str) else t.end_time
                day = start.date()
                duration = (end - start).total_seconds()
                daily_logs[day] += duration
            except Exception:
                continue

    today = datetime.today().date()
    last_7_days = [today - timedelta(days=i) for i in reversed(range(7))]

    line_chart_labels = [day.strftime("%a") for day in last_7_days]
    line_chart_values = [round(daily_logs.get(day, 0) / 3600, 2) for day in last_7_days]

    line_chart_data = {
        "labels": line_chart_labels,
        "datasets": [{
            "label": "Hours",
            "data": line_chart_values,
            "backgroundColor": "rgba(75,192,192,0.4)",
            "borderColor": "rgba(75,192,192,1)",
            "fill": False,
        }]
    }

    doughnut_data = {
        "labels": ["In Progress", "Completed", "Not Started"],
        "datasets": [{
            "data": [
                db.query(Project).filter(Project.assigned_persons == username, Project.project_status == "In Progress").count(),
                db.query(Project).filter(Project.assigned_persons == username, Project.project_status == "Completed").count(),
                db.query(Project).filter(Project.assigned_persons == username, Project.project_status == "Not Started").count(),
            ],
            "backgroundColor": ["#ffc107", "#28a745", "red"],
        }]
    }

    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        },
        "my_tasks_count": total_tasks,
        "completed_tasks": completed_tasks,
        "assigned_projects": assigned_projects,
        "hours_logged": hours_logged,
        "my_tasks": task_rows,
        "login_time": login_time,
        "logout_time": logout_time,
        "line_chart_data": line_chart_data,
        "doughnut_data": doughnut_data,
        "recent_activities": [
            {
                "id": p.id,
                "project_code": p.project_code,
                "project_name": p.project_name,
                "project_status": p.project_status
            }
            for p in recent_activities
        ]
    }


# Employee projects
@router.get("/employee-projects")
def employee_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    
    timer = None
    parse_dt = parser.parse

    if not current_user.first_name:
        raise HTTPException(status_code=400, detail="User first name missing")
        
    projects = db.query(Project).filter(Project.assigned_persons.contains(current_user.first_name)).all()

    for project in projects:
        timer = db.query(ProjectTimer).filter(
            ProjectTimer.project_id == project.id,
            ProjectTimer.employee_username == current_user.username,
            ProjectTimer.end_time == None
        ).first()

        project.is_timer_running = bool(timer)
        
        if timer:
            start = timer.start_time
            # Convert string to datetime
            if isinstance(start, str):
                start = parse_dt(start) if parse_dt else datetime.fromisoformat(start)
            now = ist_now()
            if getattr(start, "tzinfo", None) is None:
                start = start.replace(tzinfo=IST)
            elapsed_seconds = int(
                (now.astimezone(dt_timezone.utc) - start.astimezone(dt_timezone.utc)).total_seconds()
            )
            project.total_seconds = (project.total_time_spent or 0) + elapsed_seconds
            project.running_start_time = start
        else:
            project.total_seconds = project.total_time_spent or 0

    return {
        "projects": [
            {
                "id": p.id,
                "project_code": p.project_code,
                "project_name": p.project_name,
                "project_status": p.project_status,
                "project_type_name": p.project_type_name,
                "assigned_persons": p.assigned_persons,
                "project_client": p.project_client,
                "is_timer_running": p.is_timer_running,
                "total_seconds": p.total_seconds,
                "running_start_time": p.running_start_time.isoformat() if hasattr(p, 'running_start_time') and p.running_start_time else None
            }
            for p in projects
        ],
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        }
    }


# Timer data
@router.get("/timer-data/{project_id}")
def get_timer_data(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    today = ist_now().date()

    today_seconds_query = db.query(
        func.coalesce(
            func.sum(
                func.timestampdiff(
                    text("SECOND"),
                    ProjectTimer.start_time,
                    ProjectTimer.end_time
                )
            ), 0
        )
    ).filter(
        ProjectTimer.project_id == project_id,
        ProjectTimer.employee_username == current_user.username,
        func.date(ProjectTimer.start_time) == today
    )

    today_seconds = today_seconds_query.scalar()
    total_seconds = project.total_time_spent or 0

    return {
        "today_seconds": int(today_seconds),
        "total_seconds": int(total_seconds)
    }


# Start timer
@router.post("/start-timer/{project_id}")
def start_timer(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    existing_timer = db.query(ProjectTimer).filter(
        ProjectTimer.project_id == project_id,
        ProjectTimer.employee_username == current_user.username,
        ProjectTimer.end_time == None
    ).first()

    if existing_timer:
        raise HTTPException(status_code=400, detail="Timer already running")

    now_ist = ist_now()

    new_timer = ProjectTimer(
        project_id=project_id,
        employee_username=current_user.username,
        start_time=now_ist,
        date=now_ist.date()
    )
    db.add(new_timer)

    if project.project_status == "Not Started":
        project.project_status = "In Progress"

    db.commit()

    total = project.total_time_spent if project.total_time_spent is not None else 0
    return {
        "message": "Timer started",
        "start_time": new_timer.start_time.isoformat(),
        "total_seconds": total
    }


# End timer
@router.post("/end-timer/{project_id}")
def end_timer(
    project_id: int,
    body: Optional[EndTimerRequest] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    timer = db.query(ProjectTimer).filter(
        ProjectTimer.project_id == project_id,
        ProjectTimer.employee_username == current_user.username,
        ProjectTimer.end_time == None
    ).first()

    if not timer:
        raise HTTPException(status_code=404, detail="No running timer found")

    now_ist = ist_now()

    timer.end_time = now_ist
    if body and body.notes is not None:
        timer.notes = body.notes
    time_spent = (timer.end_time - timer.start_time).total_seconds()
    project.total_time_spent = (project.total_time_spent or 0) + int(time_spent)

    db.commit()

    return {
        "message": "Timer ended",
        "total_time_spent": project.total_time_spent,
        "notes": timer.notes,
    }


# Manual Log Time
@router.post("/manual-log-time/{project_id}")
def log_manual_time(
    project_id: int,
    log_data: ManualLogTime,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        date_obj = datetime.strptime(log_data.log_date, "%Y-%m-%d").date()
        start_dt = datetime.strptime(log_data.start_time, "%H:%M")
        end_dt = datetime.strptime(log_data.end_time, "%H:%M")

        start_utc = datetime.combine(date_obj, start_dt.time())
        end_utc = datetime.combine(date_obj, end_dt.time())
        if end_utc <= start_utc:
            raise ValueError("End time must be after start time")

        time_spent = (end_utc - start_utc).total_seconds()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    timer = ProjectTimer(
        project_id=project_id,
        employee_username=current_user.username,
        start_time=start_utc,
        end_time=end_utc,
        date=date_obj,
        notes=log_data.notes,
    )
    db.add(timer)

    project.total_time_spent = (project.total_time_spent or 0) + int(time_spent)
    if project.project_status == "Not Started":
        project.project_status = "In Progress"

    db.commit()

    return {
        "message": "Time logged successfully",
        "duration_seconds": time_spent,
        "notes": timer.notes,
    }


@router.get("/login-history")
def login_history(
    month: Optional[int] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "Employee":
        raise HTTPException(status_code=403, detail="Access forbidden")

    username = current_user.username
    today = datetime.today()
    
    try:
        month = int(month) if month else today.month
        year = int(year) if year else today.year
    except Exception:
        month = today.month
        year = today.year

    from calendar import monthrange
    start_date = datetime(year, month, 1).date()
    last_day = monthrange(year, month)[1]
    end_date = datetime(year, month, last_day).date()

    logs = db.query(Attendance).filter(
        Attendance.username == username,
        Attendance.date >= start_date,
        Attendance.date <= end_date
    ).order_by(Attendance.date.desc()).all()

    attendance_logs = [
        {
            "date": log.date.strftime("%d-%m-%Y") if log.date else None,
            "login_time": log.login_time.strftime("%H:%M:%S") if log.login_time else None,
            "logout_time": log.logout_time.strftime("%H:%M:%S") if log.logout_time else None,
            "total_hours": round((log.logout_time - log.login_time).total_seconds() / 3600, 2)
            if log.logout_time and log.login_time else None
        }
        for log in logs
    ]

    return {
        "attendance_logs": attendance_logs,
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        },
        "month": month,
        "year": year
    }

    
@router.get("/employee-projects-time")
def my_projects_time(
    date_str: Optional[str] = None,
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "Employee":
        raise HTTPException(status_code=403, detail="Access forbidden")

    today = datetime.today().date()
    selected_date = today
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            pass

    timer_query = db.query(ProjectTimer).filter(
        ProjectTimer.date == selected_date,
        ProjectTimer.employee_username == current_user.username
    )

    if project_id:
        try:
            project_id = int(project_id)
            timer_query = timer_query.filter(ProjectTimer.project_id == project_id)
        except:
            pass

    timers = timer_query.all()

    project_ids = {t.project_id for t in timers}
    projects = db.query(Project).filter(Project.id.in_(project_ids)).all() if project_ids else []
    project_dict = {p.id: {"name": p.project_name, "code": p.project_code} for p in projects}

    user_full_name = f"{current_user.first_name} {current_user.last_name}".strip()
    grouped_data = {
        current_user.username: {
            "employee_name": user_full_name or current_user.username,
            "timers": []
        }
    }
    
    for t in timers:
        start_dt = get_datetime(t.start_time)
        end_dt = get_datetime(t.end_time)
        duration = round(((end_dt - start_dt).total_seconds() / 3600), 2) if start_dt and end_dt else None
        record = {
            "project_name": project_dict.get(t.project_id, {}).get("name", "N/A"),
            "project_code": project_dict.get(t.project_id, {}).get("code", "N/A"),
            "start_time": format_time(t.start_time),
            "end_time": format_time(t.end_time),
            "duration": duration,
            "notes": t.notes,
        }
        grouped_data[current_user.username]["timers"].append(record)

    all_projects = db.query(Project).filter(Project.assigned_persons.like(f"%{current_user.first_name}%")).all()

    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        },
        "grouped_data": grouped_data,
        "projects": [
            {
                "id": p.id,
                "project_code": p.project_code,
                "project_name": p.project_name
            }
            for p in all_projects
        ],
        "selected_date": selected_date.strftime("%Y-%m-%d"),
        "selected_project_id": int(project_id) if project_id else None
    }
