from typing import Optional, List
from pydantic import BaseModel, HttpUrl, field_validator
from datetime import datetime, date


# ----- Lead tasks (for /tasks/by-lead/{lead_id}) -----
class LeadTaskBase(BaseModel):
    lead_id: int
    title: str
    due_date: Optional[date] = None
    assigned_to: Optional[int] = None


class LeadTaskCreate(LeadTaskBase):
    pass


class LeadTaskOut(LeadTaskBase):
    id: int
    completed: bool = False
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LeadTaskUpdate(BaseModel):
    title: Optional[str] = None
    due_date: Optional[date] = None
    assigned_to: Optional[int] = None
    completed: Optional[bool] = None


# ----- Assignment tasks (Tasks module: Client > Project > Assignment > Task) -----
class TaskAssigneeOut(BaseModel):
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    class Config:
        from_attributes = True


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    client_id: int
    project_id: Optional[int] = None
    assignment_id: int
    assignee_ids: Optional[List[int]] = None  # multiple assignees: [1, 2, 3]
    assigned_to_group_id: Optional[int] = None
    due_date: Optional[date] = None
    priority: str = "Normal"
    estimated_hours: float = 0
    actual_hours: float = 0
    brief_link: Optional[str] = None
    resources_link: Optional[str] = None
    client_folder_link: Optional[str] = None
    work_link: Optional[str] = None

    @field_validator("assignee_ids", mode="before")
    @classmethod
    def assignee_ids_to_list(cls, v):
        if v is None:
            return None
        if isinstance(v, int):
            return [v]
        return list(v) if v else []


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    client_id: Optional[int] = None
    project_id: Optional[int] = None
    assignment_id: Optional[int] = None
    assignee_ids: Optional[List[int]] = None  # multiple assignees: [1, 2, 3]; [] clears all
    assigned_to_group_id: Optional[int] = None
    due_date: Optional[date] = None

    @field_validator("assignee_ids", mode="before")
    @classmethod
    def assignee_ids_to_list(cls, v):
        if v is None:
            return None
        if isinstance(v, int):
            return [v]
        return list(v) if v else []
    priority: Optional[str] = None
    status: Optional[str] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    brief_link: Optional[str] = None
    resources_link: Optional[str] = None
    client_folder_link: Optional[str] = None
    work_link: Optional[str] = None
    is_active: Optional[bool] = None


class TaskOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    client_id: int
    project_id: Optional[int] = None
    assignment_id: int
    due_date: Optional[str] = None  # ISO date string from API
    priority: str
    status: str
    estimated_hours: float
    actual_hours: float
    brief_link: Optional[str] = None
    resources_link: Optional[str] = None
    client_folder_link: Optional[str] = None
    work_link: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    client_name: Optional[str] = None
    project_name: Optional[str] = None
    project_code: Optional[str] = None
    assignment_title: Optional[str] = None
    assigned_users: List[TaskAssigneeOut] = []

    class Config:
        from_attributes = True


class PaginatedTaskOut(BaseModel):
    items: List[TaskOut]
    total: int
    page: int
    limit: int
    total_pending: int
    total_in_progress: int
    total_completed: int
    total_estimated_hours: float
    total_actual_hours: float


class TaskStats(BaseModel):
    total: int
    pending: int
    in_progress: int
    completed: int
    estimated_hours: float
    actual_hours: float
