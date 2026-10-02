from pydantic import AliasChoices, BaseModel, Field
from typing import Optional, List
from datetime import datetime, date


class LeadTaskOut(BaseModel):
    """Task summary for display in leads list."""
    id: int
    title: str
    due_date: Optional[date] = None
    completed: bool = False
    assigned_to: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LeadNoteOut(BaseModel):
    """Note summary for display in leads list."""
    id: int
    content: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class LeadBase(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = "New"  # e.g., New, Contacted, Qualified
    priority: Optional[str] = "Medium"  # High, Medium, Low
    campaign_id: Optional[int] = None
    assigned_to_id: Optional[int] = None
    assigned_to_ids: Optional[List[int]] = None
    assigned_to_group_id: Optional[int] = None
    tags: Optional[List[str]] = []
    sheets_lead_id: Optional[str] = None
    ad_name: Optional[str] = None
    platform: Optional[str] = None
    what_best_describes_your_role: Optional[str] = None
    what_would_you_most_like_to_improve_right_now: Optional[str] = None
    when_are_you_planning_to_upgrade_or_adopt_clinic_software: Optional[str] = None
    city: Optional[str] = None
    lead_date: Optional[datetime] = None
    source: Optional[str] = None
    row_color: Optional[str] = None

class LeadCreate(LeadBase):
    pass

class LeadUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    campaign_id: Optional[int] = None
    assigned_to_id: Optional[int] = None
    assigned_to_ids: Optional[List[int]] = None
    assigned_to_group_id: Optional[int] = None
    tags: Optional[List[str]] = None
    sheets_lead_id: Optional[str] = None
    ad_name: Optional[str] = None
    platform: Optional[str] = None
    what_best_describes_your_role: Optional[str] = None
    what_would_you_most_like_to_improve_right_now: Optional[str] = None
    when_are_you_planning_to_upgrade_or_adopt_clinic_software: Optional[str] = None
    city: Optional[str] = None
    lead_date: Optional[datetime] = None
    source: Optional[str] = None
    row_color: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("row_color", "rowColor", "highlight_color"),
    )

class LeadOut(LeadBase):
    id: int
    date_created: datetime
    date_updated: Optional[datetime] = None
    lead_date: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    call_count: int = 0
    whatsapp_count: int = 0
    assigned_to_username: Optional[str] = None
    assigned_users: Optional[List[dict]] = []
    tasks: Optional[List[LeadTaskOut]] = []
    notes: Optional[List[LeadNoteOut]] = []

    class Config:
        from_attributes = True


class TagSchema(BaseModel):
    name: str
