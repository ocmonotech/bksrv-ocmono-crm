from typing import Optional, List
from pydantic import BaseModel, field_validator
from datetime import datetime, date, time


class TodoAssigneeOut(BaseModel):
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    class Config:
        from_attributes = True


class TodoCreate(BaseModel):
    title: str
    due_date: Optional[date] = None
    due_time: Optional[str] = None  # "HH:MM"
    priority: str = "Normal"
    list_name: str = "Default"
    notes: Optional[str] = None
    assignee_ids: Optional[List[int]] = None
    assigned_to_group_id: Optional[int] = None
    recurrence_interval: str = "none"  # none, daily, weekly, monthly
    reminder_days_before: Optional[int] = None  # for weekly/monthly

    @field_validator("assignee_ids", mode="before")
    @classmethod
    def assignee_ids_to_list(cls, v):
        if v is None:
            return None
        if isinstance(v, int):
            return [v]
        return list(v) if v else []


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    due_date: Optional[date] = None
    due_time: Optional[str] = None
    priority: Optional[str] = None
    list_name: Optional[str] = None
    notes: Optional[str] = None
    assignee_ids: Optional[List[int]] = None
    assigned_to_group_id: Optional[int] = None
    recurrence_interval: Optional[str] = None
    reminder_days_before: Optional[int] = None
    completed: Optional[bool] = None  # true = set completed_at to now, false = clear completed_at

class TodoOut(BaseModel):
    id: int
    title: str
    due_date: Optional[str] = None  # ISO date string
    due_time: Optional[str] = None  # "HH:MM"
    priority: str
    list_name: str
    notes: Optional[str] = None
    recurrence_interval: str
    reminder_days_before: Optional[int] = None
    created_by_id: Optional[int] = None
    created_by: Optional[TodoAssigneeOut] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    assigned_users: List[TodoAssigneeOut] = []

    class Config:
        from_attributes = True
