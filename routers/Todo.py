from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import asc, desc
from database import get_db
from models.TodoModel import Todo
from models.UsersModel import User
from models.UserGroupModel import UserGroup
from schemas.TodoSchema import TodoCreate, TodoUpdate, TodoOut, TodoAssigneeOut
from routers.auth import get_current_user, get_admin_user
from utils.notifications import create_notification
from utils.activity import set_activity_description, describe_created, describe_updated, describe_deleted
from typing import Optional, List
from datetime import date, time, datetime
from utils.datetime_utils import ist_now

router = APIRouter(prefix="/todos", tags=["Todos"])


def _todo_to_out(t: Todo) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "due_time": t.due_time.strftime("%H:%M") if t.due_time else None,
        "priority": t.priority or "Normal",
        "list_name": t.list_name or "Default",
        "notes": t.notes,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "recurrence_interval": t.recurrence_interval or "none",
        "reminder_days_before": t.reminder_days_before,
        "created_by_id": t.created_by_id,
        "created_by": (
            {
                "id": t.created_by.id,
                "username": t.created_by.username,
                "first_name": t.created_by.first_name,
                "last_name": t.created_by.last_name,
            }
            if getattr(t, "created_by", None)
            else None
        ),
        "created_at": t.created_at,
        "updated_at": t.updated_at,
        "assigned_users": [
            {"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name}
            for u in (t.assigned_users or [])
        ],
    }


# Allowed sort columns for todo-list
TODO_SORT_COLUMNS = {"due_date", "created_at", "updated_at", "title", "priority", "list_name"}


@router.get("/todo-list", response_model=List[TodoOut])
def list_todos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    list_name: Optional[str] = Query(None),
    assignee_id: Optional[int] = Query(None),
    recurrence_interval: Optional[str] = Query(None),
    completed: Optional[bool] = Query(None, description="true=completed only, false=incomplete only"),
    priority: Optional[str] = Query(None),
    sort_by: str = Query("due_date", description="Sort column: due_date, created_at, updated_at, title, priority, list_name"),
    order: str = Query("asc", description="Sort order: asc or desc"),
    limit: int = Query(100, ge=1, le=500, description="Max number of todos to return"),
):
    query = db.query(Todo).filter(Todo.is_deleted == False)
    if list_name:
        query = query.filter(Todo.list_name == list_name)
    if assignee_id is not None:
        query = query.join(Todo.assigned_users).filter(User.id == assignee_id).distinct()
    if recurrence_interval:
        query = query.filter(Todo.recurrence_interval == recurrence_interval)
    if completed is not None:
        if completed:
            query = query.filter(Todo.completed_at.isnot(None))
        else:
            query = query.filter(Todo.completed_at.is_(None))
    if priority:
        query = query.filter(Todo.priority == priority)

    sort_col = getattr(Todo, sort_by, Todo.due_date) if sort_by in TODO_SORT_COLUMNS else Todo.due_date
    if order == "desc":
        query = query.order_by(desc(sort_col), Todo.created_at.desc())
    else:
        query = query.order_by(asc(sort_col), Todo.created_at.asc())

    todos = query.limit(limit).all()
    return [_todo_to_out(t) for t in todos]


@router.get("/{todo_id}", response_model=TodoOut)
def get_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    todo = db.query(Todo).filter(Todo.id == todo_id, Todo.is_deleted == False).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return _todo_to_out(todo)


@router.post("/create-todo", response_model=TodoOut, status_code=201)
def create_todo(
    request: Request,
    data: TodoCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    due_time_obj = None
    if data.due_time:
        try:
            due_time_obj = datetime.strptime(data.due_time, "%H:%M").time()
        except ValueError:
            pass
    todo = Todo(
        title=data.title,
        due_date=data.due_date,
        due_time=due_time_obj,
        priority=data.priority or "Normal",
        list_name=data.list_name or "Default",
        notes=data.notes,
        recurrence_interval=data.recurrence_interval or "none",
        reminder_days_before=data.reminder_days_before,
        created_by_id=current_user.id,
    )
    db.add(todo)
    db.flush()
    if data.assigned_to_group_id is not None:
        group = db.query(UserGroup).filter(UserGroup.id == data.assigned_to_group_id, UserGroup.is_deleted == False).first()
        if not group:
            raise HTTPException(status_code=400, detail="User group not found")
        todo.assigned_users = [u for u in group.members if not getattr(u, "is_deleted", False)]
    elif data.assignee_ids:
        users = db.query(User).filter(User.id.in_(data.assignee_ids)).all()
        todo.assigned_users = users
    db.commit()
    db.refresh(todo)
    for user in todo.assigned_users or []:
        create_notification(
            db,
            user.id,
            f"New todo assigned: {todo.title}",
            notif_type="todo",
            target_url=f"/todos/{todo.id}",
            entity_id=todo.id,
        )
    set_activity_description(request, describe_created("todo", f"#{todo.id}", todo.title))
    return _todo_to_out(todo)


# Fields on Todo that are allowed to be updated via PUT (excludes id, created_at, created_by_id, etc.)
TODO_UPDATEABLE_FIELDS = {"title", "due_date", "priority", "list_name", "notes", "recurrence_interval", "reminder_days_before"}


@router.put("/update-todo/{todo_id}", response_model=TodoOut)
def update_todo(
    request: Request,
    todo_id: int,
    data: TodoUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    todo = db.query(Todo).filter(Todo.id == todo_id, Todo.is_deleted == False).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    old_assigned_ids = {u.id for u in todo.assigned_users}
    # Only fields that were sent in the request (exclude_unset=True)
    payload = data.model_dump(exclude_unset=True)
    assignee_ids = payload.pop("assignee_ids", None)
    assigned_to_group_id = payload.pop("assigned_to_group_id", None)
    due_time_str = payload.pop("due_time", None)
    completed = payload.pop("completed", None)

    for key, value in payload.items():
        if key in TODO_UPDATEABLE_FIELDS:
            setattr(todo, key, value)

    if due_time_str is not None:
        try:
            todo.due_time = datetime.strptime(due_time_str, "%H:%M").time()
        except (ValueError, TypeError):
            todo.due_time = None

    if assigned_to_group_id is not None:
        group = db.query(UserGroup).filter(UserGroup.id == assigned_to_group_id, UserGroup.is_deleted == False).first()
        if not group:
            raise HTTPException(status_code=400, detail="User group not found")
        todo.assigned_users = [u for u in group.members if not getattr(u, "is_deleted", False)]
    elif assignee_ids is not None:
        todo.assigned_users = db.query(User).filter(User.id.in_(assignee_ids)).all() if assignee_ids else []

    # Frontend sends completed: true/false; we persist as completed_at (set or clear)
    if completed is not None:
        if completed:
            # Store IST as naive datetime for MySQL DATETIME compatibility.
            todo.completed_at = ist_now()
        else:
            todo.completed_at = None

    db.commit()
    db.refresh(todo)
    if assignee_ids is not None or assigned_to_group_id is not None:
        new_assigned_ids = {u.id for u in todo.assigned_users}
        newly_assigned = new_assigned_ids - old_assigned_ids
        for user in todo.assigned_users or []:
            if user.id in newly_assigned:
                create_notification(
                    db,
                    user.id,
                    f"You were assigned a todo: {todo.title}",
                    notif_type="todo",
                    target_url=f"/todos/{todo.id}",
                    entity_id=todo.id,
                )
    changed = ", ".join(payload.keys()) or "details"
    if assignee_ids is not None:
        changed += ", assignees"
    if completed is not None:
        changed += ", completed"
    set_activity_description(request, describe_updated("todo", f"#{todo_id}", changed))
    return _todo_to_out(todo)


@router.delete("/delete-todo/{todo_id}", status_code=204)
def delete_todo(
    request: Request,
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    todo = db.query(Todo).filter(Todo.id == todo_id, Todo.is_deleted == False).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    title = todo.title
    todo.is_deleted = True
    todo.deleted_at = ist_now()
    db.commit()
    set_activity_description(request, describe_deleted("todo", f"#{todo_id}", title))
    return None


@router.delete("/delete-todo/{todo_id}/hard-delete", status_code=204)
def hard_delete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    db.delete(todo)
    db.commit()
    return None


@router.patch("/{todo_id}/complete", response_model=TodoOut)
def toggle_todo_complete(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle completed state: if currently complete (completed_at set), clear it; otherwise set completed_at to now."""
    todo = db.query(Todo).filter(Todo.id == todo_id, Todo.is_deleted == False).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    if todo.completed_at is not None:
        todo.completed_at = None
    else:
        todo.completed_at = ist_now()
    db.commit()
    db.refresh(todo)
    return _todo_to_out(todo)
