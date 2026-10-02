from pydantic import BaseModel, EmailStr, model_validator
from typing import Optional, List, Any
from datetime import date, time, datetime

class ProjectBookingLinkCreate(BaseModel):
    project_id: int
    is_enabled: Optional[bool] = True

class ProjectBookingLinkOut(BaseModel):
    id: int
    project_id: int
    unique_token: str
    booking_url: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AppointmentSlotCreate(BaseModel):
    project_id: int
    booking_link_id: int
    slot_date: date
    start_time: str  # Format: "HH:MM"
    end_time: str    # Format: "HH:MM"
    max_bookings: Optional[int] = 1

class AppointmentSlotUpdate(BaseModel):
    slot_date: Optional[date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    max_bookings: Optional[int] = None
    is_booked: Optional[bool] = None

class AppointmentSlotOut(BaseModel):
    id: int
    project_id: int
    booking_link_id: int
    slot_date: date
    start_time: str
    end_time: str
    is_booked: bool
    max_bookings: int
    current_bookings: int
    available: bool
    created_at: datetime

    class Config:
        from_attributes = True

class TimeSlot(BaseModel):
    start_time: str  # Format: "HH:MM"
    end_time: str    # Format: "HH:MM"
    max_bookings: Optional[int] = 1

class DayWiseSlot(BaseModel):
    slot_date: date
    time_slots: List[TimeSlot]  # Multiple time slots for this day

class RecurringSlotCreate(BaseModel):
    project_id: int
    booking_link_id: int
    days_of_week: List[int]  # 0=Monday, 1=Tuesday, ..., 6=Sunday
    start_date: date  # Start date for recurring slots
    end_date: date  # End date for recurring slots
    time_slots: List[TimeSlot]  # Same time slots for all selected days

class BulkSlotCreate(BaseModel):
    project_id: int
    booking_link_id: int
    day_wise_slots: List[DayWiseSlot]  # Multiple days with their time slots

class BulkSlotCreateResponse(BaseModel):
    created_count: int
    skipped_count: int
    errors: List[str]
    created_slots: List[AppointmentSlotOut]

class AppointmentBookingCreate(BaseModel):
    """Book a slot. Prefer sending booking_date + start_time + end_time (HH:MM); slot_id is optional for slot matching."""
    slot_id: Optional[int] = None
    booking_date: Optional[date] = None
    start_time: Optional[str] = None  # "HH:MM"
    end_time: Optional[str] = None
    # Required when slot_id is omitted (to find the matching slot row)
    project_id: Optional[int] = None
    booking_link_id: Optional[int] = None
    customer_name: str
    customer_email: EmailStr
    customer_phone: Optional[str] = None
    notes: Optional[str] = None

class AppointmentBookingOut(BaseModel):
    id: int
    slot_id: int
    project_id: int
    booking_date: Optional[date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    customer_name: str
    customer_email: str
    customer_phone: Optional[str]
    notes: Optional[str]
    booking_status: str
    created_at: datetime

    class Config:
        from_attributes = True

    @staticmethod
    def _fmt_time(t: Any) -> Optional[str]:
        if t is None:
            return None
        if isinstance(t, time):
            return t.strftime("%H:%M")
        return str(t)[:5]

    @model_validator(mode="before")
    @classmethod
    def _coerce_from_orm(cls, data: Any) -> Any:
        if not hasattr(data, "__table__"):
            return data
        slot = getattr(data, "slot", None)
        bd = getattr(data, "booking_date", None) or (slot.slot_date if slot else None)
        st = getattr(data, "start_time", None)
        et = getattr(data, "end_time", None)
        return {
            "id": data.id,
            "slot_id": data.slot_id,
            "project_id": data.project_id,
            "booking_date": bd,
            "start_time": cls._fmt_time(st) or (cls._fmt_time(slot.start_time) if slot else None),
            "end_time": cls._fmt_time(et) or (cls._fmt_time(slot.end_time) if slot else None),
            "customer_name": data.customer_name,
            "customer_email": data.customer_email,
            "customer_phone": data.customer_phone,
            "notes": data.notes,
            "booking_status": data.booking_status,
            "created_at": data.created_at,
        }

class BookingFormResponse(BaseModel):
    project_name: str
    project_code: str
    booking_link_id: int
    available_slots: List[AppointmentSlotOut]
    is_enabled: bool

