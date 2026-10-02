from typing import Optional, List
from pydantic import BaseModel, field_validator
from datetime import date, datetime


class ReminderAssigneeOut(BaseModel):
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    class Config:
        from_attributes = True


class ReminderCreate(BaseModel):
    title: str
    notes: Optional[str] = None
    frequency: str = "once"  # daily | weekly | monthly | once
    reminder_date: Optional[date] = None
    reminder_time: Optional[str] = None  # "HH:MM"
    day_of_week: Optional[int] = None   # 1=Monday .. 7=Sunday (weekly)
    day_of_month: Optional[int] = None  # 1-31 (monthly)
    assignee_ids: Optional[List[int]] = None  # defaults to current user when omitted

    @field_validator("assignee_ids", mode="before")
    @classmethod
    def assignee_ids_to_list(cls, v):
        if v is None:
            return None
        if isinstance(v, int):
            return [v]
        return list(v) if v else []

    @field_validator("frequency")
    @classmethod
    def frequency_allowed(cls, v: str) -> str:
        allowed = {"daily", "weekly", "monthly", "once"}
        if v.lower() not in allowed:
            raise ValueError("frequency must be one of: daily, weekly, monthly, once")
        return v.lower()

    @field_validator("day_of_week")
    @classmethod
    def day_of_week_range(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if not 1 <= v <= 7:
            raise ValueError("day_of_week must be 1-7 (1=Monday, 7=Sunday)")
        return v

    @field_validator("day_of_month")
    @classmethod
    def day_of_month_range(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if not 1 <= v <= 31:
            raise ValueError("day_of_month must be 1-31")
        return v


class ReminderUpdate(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None
    frequency: Optional[str] = None
    reminder_date: Optional[date] = None
    reminder_time: Optional[str] = None
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    is_active: Optional[bool] = None
    assignee_ids: Optional[List[int]] = None

    @field_validator("assignee_ids", mode="before")
    @classmethod
    def assignee_ids_to_list(cls, v):
        if v is None:
            return None
        if isinstance(v, int):
            return [v]
        return list(v) if v else []

    @field_validator("frequency")
    @classmethod
    def frequency_allowed(cls, v: Optional[str]) -> Optional[str]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        allowed = {"daily", "weekly", "monthly", "once"}
        if v.strip().lower() not in allowed:
            raise ValueError("frequency must be one of: daily, weekly, monthly, once")
        return v.strip().lower()

    @field_validator("day_of_week")
    @classmethod
    def day_of_week_range(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if not 1 <= v <= 7:
            raise ValueError("day_of_week must be 1-7")
        return v

    @field_validator("day_of_month")
    @classmethod
    def day_of_month_range(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if not 1 <= v <= 31:
            raise ValueError("day_of_month must be 1-31")
        return v


class ReminderSnoozeRequest(BaseModel):
    """Snooze like an alarm: relative duration, absolute date/time, or preset."""
    minutes: Optional[int] = None
    hours: Optional[int] = None
    days: Optional[int] = None
    until_date: Optional[date] = None
    until_time: Optional[str] = None  # "HH:MM"
    preset: Optional[str] = None  # 5m | 15m | 30m | 1h | 3h | 1d | tomorrow

    @field_validator("preset")
    @classmethod
    def preset_allowed(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        allowed = {"5m", "15m", "30m", "1h", "3h", "1d", "tomorrow"}
        key = str(v).strip().lower()
        if key not in allowed:
            raise ValueError(f"preset must be one of: {', '.join(sorted(allowed))}")
        return key


class ReminderOut(BaseModel):
    id: int
    user_id: int
    created_by_id: Optional[int] = None
    created_by: Optional[ReminderAssigneeOut] = None
    title: str
    notes: Optional[str] = None
    frequency: str
    reminder_date: Optional[str] = None
    reminder_time: Optional[str] = None
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    is_active: bool
    assigned_users: List[ReminderAssigneeOut] = []
    next_trigger_at: Optional[datetime] = None
    is_due: bool = False
    is_snoozed: bool = False
    snoozed_until: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
