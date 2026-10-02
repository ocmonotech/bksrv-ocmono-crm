import os
from pydantic import BaseModel, EmailStr, model_validator
from typing import Optional, List, Any
from datetime import date, time, datetime

# Public site base for booking links and uploaded logos in API responses (override with BKCRM_PUBLIC_BASE)
BOOKING_LINK_PUBLIC_BASE = os.environ.get("BKCRM_PUBLIC_BASE", "https://bkcrm.ocmono.com").rstrip("/")


def public_booking_logo_url(stored: Optional[str]) -> Optional[str]:
    """Turn stored path (/static/...) or external URL into absolute URL for clients."""
    if stored is None or not str(stored).strip():
        return None
    s = str(stored).strip()
    if s.startswith("http://") or s.startswith("https://"):
        return s
    path = s if s.startswith("/") else f"/{s}"
    return f"{BOOKING_LINK_PUBLIC_BASE}{path}"


def normalize_stored_logo_url(value: Optional[str]) -> Optional[str]:
    """Store relative /static/... in DB when user passes full bkcrm URL; keep external URLs as-is."""
    if value is None or not str(value).strip():
        return None
    s = str(value).strip()
    prefix = f"{BOOKING_LINK_PUBLIC_BASE}/"
    if s.startswith(prefix):
        return "/" + s[len(prefix) :].lstrip("/")
    if s.startswith(BOOKING_LINK_PUBLIC_BASE) and len(s) > len(BOOKING_LINK_PUBLIC_BASE):
        rest = s[len(BOOKING_LINK_PUBLIC_BASE) :]
        return rest if rest.startswith("/") else f"/{rest}"
    return s


class CampaignBookingLinkCreate(BaseModel):
    campaign_id: int
    is_enabled: Optional[bool] = True
    title: Optional[str] = None  # Shown on booking page; stored as page_title
    logo_url: Optional[str] = None  # URL to logo image (e.g. CDN or uploaded file URL)


class CampaignBookingLinkUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    title: Optional[str] = None
    logo_url: Optional[str] = None


class CampaignBookingLinkOut(BaseModel):
    id: int
    campaign_id: int
    unique_token: str
    booking_url: str
    title: Optional[str] = None  # from page_title
    logo_url: Optional[str] = None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @model_validator(mode="after")
    def _ensure_absolute_logo(self):
        pub = public_booking_logo_url(self.logo_url)
        if pub == self.logo_url:
            return self
        return self.model_copy(update={"logo_url": pub})

    @model_validator(mode="before")
    @classmethod
    def _map_from_orm(cls, data: Any) -> Any:
        if not hasattr(data, "__table__"):
            return data
        token = data.unique_token
        booking_url = (
            f"{BOOKING_LINK_PUBLIC_BASE}/campaign-booking/book/{token}"
            if token
            else (data.booking_url or "")
        )
        return {
            "id": data.id,
            "campaign_id": data.campaign_id,
            "unique_token": data.unique_token,
            "booking_url": booking_url,
            "title": getattr(data, "page_title", None),
            "logo_url": public_booking_logo_url(getattr(data, "logo_url", None)),
            "is_enabled": bool(data.is_enabled),
            "created_at": data.created_at,
            "updated_at": data.updated_at,
        }


class CampaignAppointmentSlotCreate(BaseModel):
    campaign_id: int
    booking_link_id: int
    slot_date: date
    start_time: str  # Format: "HH:MM"
    end_time: str   # Format: "HH:MM"
    max_bookings: Optional[int] = 1


class CampaignAppointmentSlotUpdate(BaseModel):
    slot_date: Optional[date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    max_bookings: Optional[int] = None
    is_booked: Optional[bool] = None


class CampaignAppointmentSlotOut(BaseModel):
    id: int
    campaign_id: int
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
    start_time: str
    end_time: str
    max_bookings: Optional[int] = 1


class DayWiseSlot(BaseModel):
    slot_date: date
    time_slots: List[TimeSlot]


# Schedule-by-day: one slot template (for recurring config UI)
class RecurringDaySlot(BaseModel):
    start_time: str  # "HH:MM" or "--:--"
    end_time: str
    duration_min: int = 30
    persons: int = 1  # max_bookings


# Schedule by weekday: 0=Monday .. 6=Sunday
class RecurringScheduleByDay(BaseModel):
    min_hours_advance: int = 2
    max_days_ahead: int = 30
    schedule_by_day: dict  # e.g. {"0": [RecurringDaySlot, ...], "1": [...], ...} 0=Mon, 6=Sun


class RecurringBookingConfigOut(BaseModel):
    campaign_id: int
    campaign_name: str
    booking_link_id: int
    min_hours_advance: int
    max_days_ahead: int
    schedule_by_day: dict  # {"0": [{ start_time, end_time, duration_min, persons }], ...}


class RecurringBookingConfigUpdate(BaseModel):
    campaign_id: int
    booking_link_id: int
    min_hours_advance: int = 2
    max_days_ahead: int = 30
    schedule_by_day: dict  # {"0": [RecurringDaySlot], "1": [], ...}


class RecurringSlotCreate(BaseModel):
    campaign_id: int
    booking_link_id: int
    days_of_week: List[int]
    start_date: date
    end_date: date
    time_slots: List[TimeSlot]


class BulkSlotCreate(BaseModel):
    campaign_id: int
    booking_link_id: int
    day_wise_slots: List[DayWiseSlot]


class BulkSlotCreateResponse(BaseModel):
    created_count: int
    skipped_count: int
    errors: List[str]
    created_slots: List[CampaignAppointmentSlotOut]


class CampaignAppointmentBookingCreate(BaseModel):
    """Book a slot. Prefer sending booking_date + start_time + end_time (HH:MM); slot_id is optional for slot matching."""
    slot_id: Optional[int] = None
    booking_date: Optional[date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    # Required when slot_id is omitted
    campaign_id: Optional[int] = None
    booking_link_id: Optional[int] = None
    customer_name: str
    customer_email: EmailStr
    customer_phone: Optional[str] = None
    notes: Optional[str] = None


class CampaignAppointmentBookingOut(BaseModel):
    id: int
    slot_id: int
    campaign_id: int
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
            "campaign_id": data.campaign_id,
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


class CampaignBookingFormResponse(BaseModel):
    campaign_name: str
    campaign_id: int
    booking_link_id: int
    title: Optional[str] = None  # Custom page title when set; else frontend may use campaign_name
    logo_url: Optional[str] = None  # Absolute URL when logo is stored under /static/...
    available_slots: List[CampaignAppointmentSlotOut]
    is_enabled: bool
