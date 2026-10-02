from typing import Optional, List
from pydantic import BaseModel, field_validator
from datetime import date, datetime

from schemas.ReminderSchema import ReminderAssigneeOut


FREQUENCY_VALUES = {"daily", "weekly", "monthly", "once"}


def _validate_frequency(v: str) -> str:
    if v.lower() not in FREQUENCY_VALUES:
        raise ValueError("frequency must be one of: daily, weekly, monthly, once")
    return v.lower()


def _validate_day_of_week(v: Optional[int]) -> Optional[int]:
    if v is None:
        return None
    if not 1 <= v <= 7:
        raise ValueError("day_of_week must be 1-7 (1=Monday, 7=Sunday)")
    return v


def _validate_day_of_month(v: Optional[int]) -> Optional[int]:
    if v is None:
        return None
    if not 1 <= v <= 31:
        raise ValueError("day_of_month must be 1-31")
    return v


class ReminderGroupSchedule(BaseModel):
    frequency: str = "once"
    reminder_date: Optional[date] = None
    reminder_time: Optional[str] = None
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None

    @field_validator("frequency")
    @classmethod
    def frequency_allowed(cls, v: str) -> str:
        return _validate_frequency(v)

    @field_validator("day_of_week")
    @classmethod
    def day_of_week_range(cls, v: Optional[int]) -> Optional[int]:
        return _validate_day_of_week(v)

    @field_validator("day_of_month")
    @classmethod
    def day_of_month_range(cls, v: Optional[int]) -> Optional[int]:
        return _validate_day_of_month(v)


class ReminderGroupItemCreate(ReminderGroupSchedule):
    title: str
    use_custom_schedule: bool = False

    @field_validator("frequency")
    @classmethod
    def frequency_optional_for_item(cls, v: str) -> str:
        return _validate_frequency(v)


class ReminderGroupItemUpdate(ReminderGroupSchedule):
    id: Optional[int] = None
    title: Optional[str] = None
    use_custom_schedule: Optional[bool] = None

    @field_validator("frequency")
    @classmethod
    def frequency_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return _validate_frequency(v.strip())


class ReminderGroupItemPatch(BaseModel):
    title: Optional[str] = None
    use_custom_schedule: Optional[bool] = None
    frequency: Optional[str] = None
    reminder_date: Optional[date] = None
    reminder_time: Optional[str] = None
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None

    @field_validator("frequency")
    @classmethod
    def frequency_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return _validate_frequency(v.strip())

    @field_validator("day_of_week")
    @classmethod
    def day_of_week_range(cls, v: Optional[int]) -> Optional[int]:
        return _validate_day_of_week(v)

    @field_validator("day_of_month")
    @classmethod
    def day_of_month_range(cls, v: Optional[int]) -> Optional[int]:
        return _validate_day_of_month(v)


class ReminderGroupCreate(ReminderGroupSchedule):
    name: str
    notes: Optional[str] = None
    assignee_ids: Optional[List[int]] = None
    items: List[ReminderGroupItemCreate]

    @field_validator("assignee_ids", mode="before")
    @classmethod
    def assignee_ids_to_list(cls, v):
        if v is None:
            return None
        if isinstance(v, int):
            return [v]
        return list(v) if v else []

    @field_validator("items")
    @classmethod
    def items_not_empty(cls, v: List[ReminderGroupItemCreate]) -> List[ReminderGroupItemCreate]:
        if not v:
            raise ValueError("At least one reminder item is required")
        return v


class ReminderGroupUpdate(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None
    frequency: Optional[str] = None
    reminder_date: Optional[date] = None
    reminder_time: Optional[str] = None
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    is_active: Optional[bool] = None
    assignee_ids: Optional[List[int]] = None
    items: Optional[List[ReminderGroupItemUpdate]] = None

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
        return _validate_frequency(v.strip())

    @field_validator("day_of_week")
    @classmethod
    def day_of_week_range(cls, v: Optional[int]) -> Optional[int]:
        return _validate_day_of_week(v)

    @field_validator("day_of_month")
    @classmethod
    def day_of_month_range(cls, v: Optional[int]) -> Optional[int]:
        return _validate_day_of_month(v)

    @field_validator("items")
    @classmethod
    def items_not_empty(cls, v: Optional[List[ReminderGroupItemUpdate]]) -> Optional[List[ReminderGroupItemUpdate]]:
        if v is not None and not v:
            raise ValueError("items cannot be empty when provided")
        return v


class ReminderGroupItemOut(BaseModel):
    id: int
    sort_order: int
    title: str
    use_custom_schedule: bool
    frequency: str
    reminder_date: Optional[str] = None
    reminder_time: Optional[str] = None
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    is_active: bool
    next_trigger_at: Optional[datetime] = None
    is_due: bool = False
    is_snoozed: bool = False
    snoozed_until: Optional[datetime] = None


class ReminderGroupOut(BaseModel):
    id: int
    name: str
    notes: Optional[str] = None
    frequency: str
    reminder_date: Optional[str] = None
    reminder_time: Optional[str] = None
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    is_active: bool
    created_by_id: Optional[int] = None
    created_by: Optional[ReminderAssigneeOut] = None
    assigned_users: List[ReminderAssigneeOut] = []
    items: List[ReminderGroupItemOut] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
