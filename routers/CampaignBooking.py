from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import and_
from database import get_db
from models.CampaignModel import Campaign
from models.CampaignBookingModel import (
    CampaignBookingLink,
    CampaignAppointmentSlot,
    CampaignAppointmentBooking,
    CampaignRecurringSchedule,
)
from models.MessageTemplateModel import MessageTemplate
from models.SettingsModel import Settings
from schemas.CampaignBookingSchema import (
    BOOKING_LINK_PUBLIC_BASE,
    normalize_stored_logo_url,
    public_booking_logo_url,
    CampaignBookingLinkCreate, CampaignBookingLinkUpdate, CampaignBookingLinkOut,
    CampaignAppointmentSlotCreate, CampaignAppointmentSlotUpdate, CampaignAppointmentSlotOut,
    CampaignAppointmentBookingCreate, CampaignAppointmentBookingOut, CampaignBookingFormResponse,
    BulkSlotCreate, BulkSlotCreateResponse, DayWiseSlot, TimeSlot, RecurringSlotCreate,
    RecurringBookingConfigOut, RecurringBookingConfigUpdate, RecurringDaySlot,
)
from routers.auth import get_current_user
from routers.Notification import send_email
from typing import List, Optional
from datetime import datetime, date, timedelta
from utils.datetime_utils import IST, ist_now, ist_today
import secrets
import re
import os
import uuid

router = APIRouter(prefix="/campaign-booking", tags=["Campaign Booking"])

# Files saved under assets/ → served at /static/... (see main.py StaticFiles)
BOOKING_LINK_LOGO_FS_DIR = os.path.join("assets", "uploads", "bookinglinklogos")
BOOKING_LINK_LOGO_URL_PREFIX = "/static/uploads/bookinglinklogos"
BOOKING_LINK_LOGO_MAX_BYTES = 5 * 1024 * 1024
BOOKING_LINK_LOGO_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _parse_hhmm(s: str):
    return datetime.strptime(s.strip(), "%H:%M").time()


def _duration_minutes(start_t, end_t) -> int:
    a = datetime.combine(date.min, start_t)
    b = datetime.combine(date.min, end_t)
    return max(0, int((b - a).total_seconds() / 60))


def _validate_campaign_booking_window(
    link: CampaignBookingLink, booking_date: date, start_t, end_t
) -> None:
    """Enforce min_hours_advance and max_days_ahead from the booking link."""
    today = ist_today()
    if booking_date < today:
        raise HTTPException(status_code=400, detail="Cannot book past dates")
    max_days = getattr(link, "max_days_ahead", None)
    if max_days is None:
        max_days = 30
    if booking_date > today + timedelta(days=max_days):
        raise HTTPException(
            status_code=400,
            detail=f"Booking date must be within {max_days} days from today",
        )
    min_h = getattr(link, "min_hours_advance", None)
    if min_h is None:
        min_h = 2
    start_dt = datetime.combine(booking_date, start_t, tzinfo=IST)
    if start_dt < ist_now() + timedelta(hours=min_h):
        raise HTTPException(
            status_code=400,
            detail=f"Appointment must be at least {min_h} hour(s) from now",
        )


def _resolve_campaign_slot_for_booking(db: Session, data: CampaignAppointmentBookingCreate):
    """
    Find the slot row that matches the user's chosen date and start/end times.
    slot_id may be wrong; matching is by campaign + booking_link + date + times.
    """
    hint = None
    if data.slot_id:
        hint = db.query(CampaignAppointmentSlot).filter(CampaignAppointmentSlot.id == data.slot_id).first()
        if not hint:
            raise HTTPException(status_code=404, detail="Slot not found")

    booking_date = data.booking_date
    start_s = data.start_time
    end_s = data.end_time
    if hint:
        if booking_date is None:
            booking_date = hint.slot_date
        if not start_s:
            start_s = hint.start_time.strftime("%H:%M")
        if not end_s:
            end_s = hint.end_time.strftime("%H:%M")

    if booking_date is None or not start_s or not end_s:
        raise HTTPException(
            status_code=400,
            detail="booking_date, start_time, and end_time are required (or provide slot_id to infer them)",
        )

    try:
        start_t = _parse_hhmm(start_s)
        end_t = _parse_hhmm(end_s)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM")

    if end_t <= start_t:
        raise HTTPException(status_code=400, detail="End time must be after start time")

    campaign_id = hint.campaign_id if hint else data.campaign_id
    booking_link_id = hint.booking_link_id if hint else data.booking_link_id
    if campaign_id is None or booking_link_id is None:
        raise HTTPException(
            status_code=400,
            detail="Provide slot_id or both campaign_id and booking_link_id with the booking date and times",
        )

    slot = (
        db.query(CampaignAppointmentSlot)
        .filter(
            CampaignAppointmentSlot.campaign_id == campaign_id,
            CampaignAppointmentSlot.booking_link_id == booking_link_id,
            CampaignAppointmentSlot.slot_date == booking_date,
            CampaignAppointmentSlot.start_time == start_t,
            CampaignAppointmentSlot.end_time == end_t,
        )
        .first()
    )
    if slot:
        return slot, booking_date, start_t, end_t

    # No pre-generated row: UI may show slots that were never persisted. Create a slot row on demand.
    link = (
        db.query(CampaignBookingLink)
        .filter(
            CampaignBookingLink.id == booking_link_id,
            CampaignBookingLink.campaign_id == campaign_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Booking link not found for this campaign")
    if not link.is_enabled:
        raise HTTPException(status_code=400, detail="Booking is disabled for this link")

    _validate_campaign_booking_window(link, booking_date, start_t, end_t)

    dur = _duration_minutes(start_t, end_t)
    slot = CampaignAppointmentSlot(
        campaign_id=campaign_id,
        booking_link_id=booking_link_id,
        slot_date=booking_date,
        start_time=start_t,
        end_time=end_t,
        duration_minutes=dur or None,
        is_booked=False,
        max_bookings=1,
        current_bookings=0,
    )
    db.add(slot)
    db.flush()

    return slot, booking_date, start_t, end_t


def replace_appointment_template_variables(content: str, appointment_data: dict) -> str:
    """Replace template variables with actual appointment data (campaign-wise)"""
    replacements = {
        '{{name}}': appointment_data.get('customer_name', ''),
        '{{customer_name}}': appointment_data.get('customer_name', ''),
        '{{email}}': appointment_data.get('customer_email', ''),
        '{{customer_email}}': appointment_data.get('customer_email', ''),
        '{{phone}}': appointment_data.get('customer_phone', ''),
        '{{customer_phone}}': appointment_data.get('customer_phone', ''),
        '{{campaign_name}}': appointment_data.get('campaign_name', ''),
        '{{project_name}}': appointment_data.get('campaign_name', ''),
        '{{project_code}}': appointment_data.get('campaign_name', ''),
        '{{slot_date}}': appointment_data.get('slot_date', ''),
        '{{appointment_date}}': appointment_data.get('slot_date', ''),
        '{{start_time}}': appointment_data.get('start_time', ''),
        '{{end_time}}': appointment_data.get('end_time', ''),
        '{{booking_status}}': appointment_data.get('booking_status', ''),
        '{{status}}': appointment_data.get('booking_status', ''),
        '{{notes}}': appointment_data.get('notes', ''),
        '{{date}}': appointment_data.get('booking_date', ''),
        '{{time}}': appointment_data.get('booking_time', ''),
        '{{booking_id}}': str(appointment_data.get('booking_id', '')),
    }
    result = content
    for var, value in replacements.items():
        result = result.replace(var, str(value))
    def replace_var(match):
        var_name = match.group(1).lower()
        return str(appointment_data.get(var_name, ''))
    result = re.sub(r'\{\{(\w+)\}\}', replace_var, result)
    return result


def send_campaign_appointment_confirmation_email(booking_id: int):
    """Send appointment confirmation email for campaign booking"""
    from database import SessionLocal
    db = SessionLocal()
    try:
        auto_email_setting = db.query(Settings).filter(Settings.key == "auto_appointment_email_enabled").first()
        if auto_email_setting and auto_email_setting.value and auto_email_setting.value.lower() == "false":
            return False
        booking = db.query(CampaignAppointmentBooking).filter(CampaignAppointmentBooking.id == booking_id).first()
        if not booking:
            return False
        slot = db.query(CampaignAppointmentSlot).filter(CampaignAppointmentSlot.id == booking.slot_id).first()
        campaign = db.query(Campaign).filter(Campaign.id == booking.campaign_id).first()
        if not campaign:
            return False
        # Prefer times stored on the booking (what the user selected); fallback to slot row
        appt_date = booking.booking_date or (slot.slot_date if slot else None)
        appt_start = booking.start_time or (slot.start_time if slot else None)
        appt_end = booking.end_time or (slot.end_time if slot else None)
        if not appt_date or not appt_start:
            return False
        setting = db.query(Settings).filter(Settings.key == "appointment_email_template_id").first()
        if not setting or not setting.value:
            return False
        template_id = int(setting.value)
        template = db.query(MessageTemplate).filter(
            MessageTemplate.id == template_id,
            MessageTemplate.template_type == "email",
            MessageTemplate.status == "Active"
        ).first()
        if not template:
            return False
        appointment_data = {
            'customer_name': booking.customer_name,
            'customer_email': booking.customer_email,
            'customer_phone': booking.customer_phone or '',
            'campaign_name': campaign.name or '',
            'slot_date': appt_date.strftime('%Y-%m-%d'),
            'start_time': appt_start.strftime('%H:%M'),
            'end_time': appt_end.strftime('%H:%M') if appt_end else '',
            'booking_status': booking.booking_status,
            'notes': booking.notes or '',
            'booking_date': booking.created_at.strftime('%Y-%m-%d') if booking.created_at else '',
            'booking_time': booking.created_at.strftime('%H:%M:%S') if booking.created_at else '',
            'booking_id': booking.id,
        }
        subject = replace_appointment_template_variables(template.subject or "Appointment Confirmation", appointment_data)
        content = replace_appointment_template_variables(template.content, appointment_data)
        success, _ = send_email(booking.customer_email, subject, content)
        template.usage_count += 1
        if success:
            template.success_count += 1
        if template.usage_count > 0:
            template.success_rate = (template.success_count / template.usage_count) * 100
        db.commit()
        return success
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def generate_unique_token() -> str:
    return secrets.token_urlsafe(32)


def _optional_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


@router.post("/generate-link", response_model=CampaignBookingLinkOut)
def generate_booking_link(
    data: CampaignBookingLinkCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    campaign = db.query(Campaign).filter(Campaign.id == data.campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    existing_link = db.query(CampaignBookingLink).filter(
        CampaignBookingLink.campaign_id == data.campaign_id
    ).first()
    if existing_link:
        existing_link.is_enabled = data.is_enabled
        if data.title is not None:
            existing_link.page_title = _optional_str(data.title)
        if data.logo_url is not None:
            existing_link.logo_url = normalize_stored_logo_url(data.logo_url)
        existing_link.updated_at = ist_now()
        db.commit()
        db.refresh(existing_link)
        return CampaignBookingLinkOut.model_validate(existing_link)
    token = generate_unique_token()
    booking_url = f"{BOOKING_LINK_PUBLIC_BASE}/campaign-booking/book/{token}"
    booking_link = CampaignBookingLink(
        campaign_id=data.campaign_id,
        unique_token=token,
        booking_url=booking_url,
        is_enabled=data.is_enabled,
        page_title=_optional_str(data.title),
        logo_url=normalize_stored_logo_url(data.logo_url) if data.logo_url is not None else None,
    )
    db.add(booking_link)
    db.commit()
    db.refresh(booking_link)
    return CampaignBookingLinkOut.model_validate(booking_link)


@router.get("/link/{campaign_id}", response_model=CampaignBookingLinkOut)
def get_booking_link(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    booking_link = db.query(CampaignBookingLink).filter(
        CampaignBookingLink.campaign_id == campaign_id
    ).first()
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found for this campaign")
    booking_link.booking_url = f"{BOOKING_LINK_PUBLIC_BASE}/campaign-booking/book/{booking_link.unique_token}"
    db.commit()
    db.refresh(booking_link)
    return CampaignBookingLinkOut.model_validate(booking_link)


@router.get("/all-links", response_model=List[CampaignBookingLinkOut])
def get_all_booking_links(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    links = db.query(CampaignBookingLink).all()
    for link in links:
        link.booking_url = f"{BOOKING_LINK_PUBLIC_BASE}/campaign-booking/book/{link.unique_token}"
    db.commit()
    return [CampaignBookingLinkOut.model_validate(link) for link in links]


@router.put("/link/{link_id}", response_model=CampaignBookingLinkOut)
async def update_booking_link(
    link_id: int,
    request: Request,
    is_enabled: Optional[bool] = Query(
        None,
        description="Deprecated: prefer JSON body.is_enabled for toggling the link",
    ),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    booking_link = db.query(CampaignBookingLink).filter(CampaignBookingLink.id == link_id).first()
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    body: dict = {}
    if request.headers.get("content-length") not in (None, "", "0"):
        try:
            body = await request.json()
            if body is None:
                body = {}
        except Exception:
            body = {}
    data = CampaignBookingLinkUpdate.model_validate(body)
    if data.is_enabled is not None:
        booking_link.is_enabled = data.is_enabled
    elif is_enabled is not None:
        booking_link.is_enabled = is_enabled
    if data.title is not None:
        booking_link.page_title = _optional_str(data.title)
    if data.logo_url is not None:
        booking_link.logo_url = normalize_stored_logo_url(data.logo_url)
    booking_link.updated_at = ist_now()
    db.commit()
    db.refresh(booking_link)
    return CampaignBookingLinkOut.model_validate(booking_link)


def _remove_booking_logo_file_if_ours(stored_url: Optional[str]) -> None:
    """Delete a previously uploaded logo file from disk (only under bookinglinklogos)."""
    if not stored_url or not str(stored_url).strip():
        return
    s = str(stored_url).strip().split("?")[0]
    if not s.startswith(BOOKING_LINK_LOGO_URL_PREFIX + "/"):
        return
    name = os.path.basename(s)
    if not name or name in (".", "..") or ".." in name:
        return
    path = os.path.join(BOOKING_LINK_LOGO_FS_DIR, name)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


@router.post("/link/{link_id}/logo", response_model=CampaignBookingLinkOut)
async def upload_booking_link_logo(
    link_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Save logo under assets/uploads/bookinglinklogos (URL /static/uploads/bookinglinklogos/...)."""
    booking_link = db.query(CampaignBookingLink).filter(CampaignBookingLink.id == link_id).first()
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found")

    raw_name = file.filename or ""
    ext = os.path.splitext(raw_name)[1].lower()
    if ext not in BOOKING_LINK_LOGO_ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image type. Allowed: {', '.join(sorted(BOOKING_LINK_LOGO_ALLOWED_EXT))}",
        )

    os.makedirs(BOOKING_LINK_LOGO_FS_DIR, exist_ok=True)
    contents = await file.read()
    if len(contents) > BOOKING_LINK_LOGO_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Logo file too large (max 5MB)")

    _remove_booking_logo_file_if_ours(booking_link.logo_url)

    fname = f"{uuid.uuid4().hex}{ext}"
    fs_path = os.path.join(BOOKING_LINK_LOGO_FS_DIR, fname)
    with open(fs_path, "wb") as out:
        out.write(contents)

    booking_link.logo_url = f"{BOOKING_LINK_LOGO_URL_PREFIX}/{fname}"
    booking_link.updated_at = ist_now()
    db.commit()
    db.refresh(booking_link)
    return CampaignBookingLinkOut.model_validate(booking_link)


@router.post("/slots", response_model=CampaignAppointmentSlotOut)
def create_appointment_slot(
    data: CampaignAppointmentSlotCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    campaign = db.query(Campaign).filter(Campaign.id == data.campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    booking_link = db.query(CampaignBookingLink).filter(
        CampaignBookingLink.id == data.booking_link_id
    ).first()
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    if booking_link.campaign_id != data.campaign_id:
        raise HTTPException(status_code=400, detail="Booking link does not belong to this campaign")
    try:
        start_time_obj = datetime.strptime(data.start_time, "%H:%M").time()
        end_time_obj = datetime.strptime(data.end_time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM format")
    if end_time_obj <= start_time_obj:
        raise HTTPException(status_code=400, detail="End time must be after start time")
    existing_slot = db.query(CampaignAppointmentSlot).filter(
        and_(
            CampaignAppointmentSlot.campaign_id == data.campaign_id,
            CampaignAppointmentSlot.slot_date == data.slot_date,
            CampaignAppointmentSlot.start_time == start_time_obj,
            CampaignAppointmentSlot.end_time == end_time_obj
        )
    ).first()
    if existing_slot:
        raise HTTPException(status_code=400, detail="Slot already exists for this date and time")
    slot = CampaignAppointmentSlot(
        campaign_id=data.campaign_id,
        booking_link_id=data.booking_link_id,
        slot_date=data.slot_date,
        start_time=start_time_obj,
        end_time=end_time_obj,
        max_bookings=data.max_bookings
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return CampaignAppointmentSlotOut(
        id=slot.id,
        campaign_id=slot.campaign_id,
        booking_link_id=slot.booking_link_id,
        slot_date=slot.slot_date,
        start_time=slot.start_time.strftime("%H:%M"),
        end_time=slot.end_time.strftime("%H:%M"),
        is_booked=slot.is_booked,
        max_bookings=slot.max_bookings,
        current_bookings=slot.current_bookings,
        available=slot.current_bookings < slot.max_bookings,
        created_at=slot.created_at
    )


def _schedule_by_day_from_schedules(schedules: list) -> dict:
    """Build schedule_by_day dict from CampaignRecurringSchedule rows. Keys "0".."6" (Mon-Sun)."""
    out = {str(d): [] for d in range(7)}
    for s in schedules:
        key = str(s.day_of_week)
        out[key].append({
            "start_time": s.start_time.strftime("%H:%M") if s.start_time else "--:--",
            "end_time": s.end_time.strftime("%H:%M") if s.end_time else "--:--",
            "duration_min": s.duration_minutes or 30,
            "persons": s.max_bookings or 1,
        })
    return out

# Get recurring booking config
@router.get("/slots/recurring", response_model=RecurringBookingConfigOut)
def get_recurring_booking_config(
    campaign_id: int = Query(..., description="Campaign ID"),
    booking_link_id: Optional[int] = Query(None, description="Booking link ID; if omitted, first link for campaign"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get recurring booking config: campaign name, booking window, and schedule by day (Mon-Sun)."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    link = None
    if booking_link_id:
        link = db.query(CampaignBookingLink).filter(
            CampaignBookingLink.id == booking_link_id,
            CampaignBookingLink.campaign_id == campaign_id,
        ).first()
    if not link:
        link = db.query(CampaignBookingLink).filter(CampaignBookingLink.campaign_id == campaign_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="No booking link found for this campaign")
    schedules = (
        db.query(CampaignRecurringSchedule)
        .filter(
            CampaignRecurringSchedule.campaign_id == campaign_id,
            CampaignRecurringSchedule.booking_link_id == link.id,
        )
        .order_by(CampaignRecurringSchedule.day_of_week, CampaignRecurringSchedule.sort_order)
        .all()
    )
    min_h = getattr(link, "min_hours_advance", None)
    max_d = getattr(link, "max_days_ahead", None)
    return RecurringBookingConfigOut(
        campaign_id=campaign_id,
        campaign_name=campaign.name or "",
        booking_link_id=link.id,
        min_hours_advance=min_h if min_h is not None else 2,
        max_days_ahead=max_d if max_d is not None else 30,
        schedule_by_day=_schedule_by_day_from_schedules(schedules),
    )

#
@router.put("/slots/recurring/update-config", response_model=RecurringBookingConfigOut)
def save_recurring_booking_config(
    data: RecurringBookingConfigUpdate,
    generate_slots: bool = Query(True, description="Generate actual slots for the next max_days_ahead days"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Save booking window and schedule-by-day config; optionally generate slots for the next N days."""
    campaign = db.query(Campaign).filter(Campaign.id == data.campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    link = db.query(CampaignBookingLink).filter(
        CampaignBookingLink.id == data.booking_link_id,
        CampaignBookingLink.campaign_id == data.campaign_id,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    link.min_hours_advance = data.min_hours_advance
    link.max_days_ahead = data.max_days_ahead
    db.flush()
    existing = (
        db.query(CampaignRecurringSchedule)
        .filter(
            CampaignRecurringSchedule.campaign_id == data.campaign_id,
            CampaignRecurringSchedule.booking_link_id == data.booking_link_id,
        )
        .all()
    )
    for e in existing:
        db.delete(e)
    db.flush()
    sort_order = 0
    for day_str, slots in data.schedule_by_day.items():
        try:
            day_of_week = int(day_str)
        except (ValueError, TypeError):
            continue
        if day_of_week < 0 or day_of_week > 6:
            continue
        for slot in slots:
            if isinstance(slot, dict):
                st = slot.get("start_time") or "--:--"
                et = slot.get("end_time") or "--:--"
                dur = slot.get("duration_min", 30)
                persons = slot.get("persons", 1)
            else:
                st = getattr(slot, "start_time", "--:--")
                et = getattr(slot, "end_time", "--:--")
                dur = getattr(slot, "duration_min", 30)
                persons = getattr(slot, "persons", 1)
            if st == "--:--" and et == "--:--":
                continue
            try:
                start_time_obj = datetime.strptime(st, "%H:%M").time()
                end_time_obj = datetime.strptime(et, "%H:%M").time()
            except ValueError:
                continue
            rec = CampaignRecurringSchedule(
                campaign_id=data.campaign_id,
                booking_link_id=data.booking_link_id,
                day_of_week=day_of_week,
                start_time=start_time_obj,
                end_time=end_time_obj,
                duration_minutes=dur,
                max_bookings=persons,
                sort_order=sort_order,
            )
            db.add(rec)
            sort_order += 1
    db.commit()
    if generate_slots:
        _generate_slots_from_recurring_config(
            db, data.campaign_id, data.booking_link_id, link.max_days_ahead
        )
    schedules = (
        db.query(CampaignRecurringSchedule)
        .filter(
            CampaignRecurringSchedule.campaign_id == data.campaign_id,
            CampaignRecurringSchedule.booking_link_id == data.booking_link_id,
        )
        .order_by(CampaignRecurringSchedule.day_of_week, CampaignRecurringSchedule.sort_order)
        .all()
    )
    return RecurringBookingConfigOut(
        campaign_id=data.campaign_id,
        campaign_name=campaign.name or "",
        booking_link_id=data.booking_link_id,
        min_hours_advance=link.min_hours_advance,
        max_days_ahead=link.max_days_ahead,
        schedule_by_day=_schedule_by_day_from_schedules(schedules),
    )


def _generate_slots_from_recurring_config(
    db: Session, campaign_id: int, booking_link_id: int, max_days: int
) -> None:
    """Create CampaignAppointmentSlot rows for the next max_days from recurring schedule templates."""
    link = db.query(CampaignBookingLink).filter(
        CampaignBookingLink.id == booking_link_id,
        CampaignBookingLink.campaign_id == campaign_id,
    ).first()
    if not link:
        return
    schedules = (
        db.query(CampaignRecurringSchedule)
        .filter(
            CampaignRecurringSchedule.campaign_id == campaign_id,
            CampaignRecurringSchedule.booking_link_id == booking_link_id,
        )
        .order_by(CampaignRecurringSchedule.day_of_week, CampaignRecurringSchedule.sort_order)
        .all()
    )
    if not schedules:
        return
    today = date.today()
    end_date = today + timedelta(days=max_days)
    current = today
    while current <= end_date:
        dow = current.weekday()
        for s in schedules:
            if s.day_of_week != dow:
                continue
            existing = db.query(CampaignAppointmentSlot).filter(
                and_(
                    CampaignAppointmentSlot.campaign_id == campaign_id,
                    CampaignAppointmentSlot.booking_link_id == booking_link_id,
                    CampaignAppointmentSlot.slot_date == current,
                    CampaignAppointmentSlot.start_time == s.start_time,
                    CampaignAppointmentSlot.end_time == s.end_time,
                )
            ).first()
            if existing:
                continue
            slot = CampaignAppointmentSlot(
                campaign_id=campaign_id,
                booking_link_id=booking_link_id,
                slot_date=current,
                start_time=s.start_time,
                end_time=s.end_time,
                duration_minutes=s.duration_minutes,
                max_bookings=s.max_bookings,
            )
            db.add(slot)
        current += timedelta(days=1)
    db.commit()


@router.post("/slots/recurring/generate", response_model=BulkSlotCreateResponse)
def create_recurring_slots(
    data: RecurringSlotCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Legacy: create recurring slots from days_of_week + date range + time_slots. Prefer PUT /slots/recurring for schedule-by-day config."""
    campaign = db.query(Campaign).filter(Campaign.id == data.campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    booking_link = db.query(CampaignBookingLink).filter(
        CampaignBookingLink.id == data.booking_link_id
    ).first()
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    if booking_link.campaign_id != data.campaign_id:
        raise HTTPException(status_code=400, detail="Booking link does not belong to this campaign")
    if data.end_date < data.start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")
    if data.start_date < date.today():
        raise HTTPException(status_code=400, detail="Start date cannot be in the past")
    created_slots = []
    skipped_count = 0
    errors = []
    current_date = data.start_date
    matching_dates = []
    while current_date <= data.end_date:
        if current_date.weekday() in data.days_of_week:
            matching_dates.append(current_date)
        current_date += timedelta(days=1)
    for slot_date in matching_dates:
        for time_slot in data.time_slots:
            try:
                start_time_obj = datetime.strptime(time_slot.start_time, "%H:%M").time()
                end_time_obj = datetime.strptime(time_slot.end_time, "%H:%M").time()
                if end_time_obj <= start_time_obj:
                    errors.append(f"End time must be after start time for {slot_date}")
                    skipped_count += 1
                    continue
                existing_slot = db.query(CampaignAppointmentSlot).filter(
                    and_(
                        CampaignAppointmentSlot.campaign_id == data.campaign_id,
                        CampaignAppointmentSlot.slot_date == slot_date,
                        CampaignAppointmentSlot.start_time == start_time_obj,
                        CampaignAppointmentSlot.end_time == end_time_obj
                    )
                ).first()
                if existing_slot:
                    skipped_count += 1
                    continue
                slot = CampaignAppointmentSlot(
                    campaign_id=data.campaign_id,
                    booking_link_id=data.booking_link_id,
                    slot_date=slot_date,
                    start_time=start_time_obj,
                    end_time=end_time_obj,
                    max_bookings=time_slot.max_bookings
                )
                db.add(slot)
                db.flush()
                created_slots.append(CampaignAppointmentSlotOut(
                    id=slot.id,
                    campaign_id=slot.campaign_id,
                    booking_link_id=slot.booking_link_id,
                    slot_date=slot.slot_date,
                    start_time=slot.start_time.strftime("%H:%M"),
                    end_time=slot.end_time.strftime("%H:%M"),
                    is_booked=slot.is_booked,
                    max_bookings=slot.max_bookings,
                    current_bookings=slot.current_bookings,
                    available=slot.current_bookings < slot.max_bookings,
                    created_at=slot.created_at
                ))
            except Exception as e:
                errors.append(str(e))
                skipped_count += 1
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return BulkSlotCreateResponse(
        created_count=len(created_slots),
        skipped_count=skipped_count,
        errors=errors,
        created_slots=created_slots
    )


@router.post("/slots/bulk", response_model=BulkSlotCreateResponse)
def bulk_create_appointment_slots(
    data: BulkSlotCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    campaign = db.query(Campaign).filter(Campaign.id == data.campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    booking_link = db.query(CampaignBookingLink).filter(
        CampaignBookingLink.id == data.booking_link_id
    ).first()
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    if booking_link.campaign_id != data.campaign_id:
        raise HTTPException(status_code=400, detail="Booking link does not belong to this campaign")
    created_slots = []
    skipped_count = 0
    errors = []
    for day_slot in data.day_wise_slots:
        if day_slot.slot_date < date.today():
            skipped_count += len(day_slot.time_slots)
            continue
        for time_slot in day_slot.time_slots:
            try:
                start_time_obj = datetime.strptime(time_slot.start_time, "%H:%M").time()
                end_time_obj = datetime.strptime(time_slot.end_time, "%H:%M").time()
                if end_time_obj <= start_time_obj:
                    skipped_count += 1
                    continue
                existing_slot = db.query(CampaignAppointmentSlot).filter(
                    and_(
                        CampaignAppointmentSlot.campaign_id == data.campaign_id,
                        CampaignAppointmentSlot.slot_date == day_slot.slot_date,
                        CampaignAppointmentSlot.start_time == start_time_obj,
                        CampaignAppointmentSlot.end_time == end_time_obj
                    )
                ).first()
                if existing_slot:
                    skipped_count += 1
                    continue
                slot = CampaignAppointmentSlot(
                    campaign_id=data.campaign_id,
                    booking_link_id=data.booking_link_id,
                    slot_date=day_slot.slot_date,
                    start_time=start_time_obj,
                    end_time=end_time_obj,
                    max_bookings=time_slot.max_bookings
                )
                db.add(slot)
                db.flush()
                created_slots.append(CampaignAppointmentSlotOut(
                    id=slot.id,
                    campaign_id=slot.campaign_id,
                    booking_link_id=slot.booking_link_id,
                    slot_date=slot.slot_date,
                    start_time=slot.start_time.strftime("%H:%M"),
                    end_time=slot.end_time.strftime("%H:%M"),
                    is_booked=slot.is_booked,
                    max_bookings=slot.max_bookings,
                    current_bookings=slot.current_bookings,
                    available=slot.current_bookings < slot.max_bookings,
                    created_at=slot.created_at
                ))
            except Exception as e:
                skipped_count += 1
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return BulkSlotCreateResponse(
        created_count=len(created_slots),
        skipped_count=skipped_count,
        errors=errors,
        created_slots=created_slots
    )


@router.get("/slots/{campaign_id}", response_model=List[CampaignAppointmentSlotOut])
def get_appointment_slots(
    campaign_id: int,
    slot_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    query = db.query(CampaignAppointmentSlot).filter(CampaignAppointmentSlot.campaign_id == campaign_id)
    if slot_date:
        query = query.filter(CampaignAppointmentSlot.slot_date == slot_date)
    else:
        query = query.filter(CampaignAppointmentSlot.slot_date >= date.today())
    slots = query.order_by(CampaignAppointmentSlot.slot_date, CampaignAppointmentSlot.start_time).all()
    return [
        CampaignAppointmentSlotOut(
            id=s.id,
            campaign_id=s.campaign_id,
            booking_link_id=s.booking_link_id,
            slot_date=s.slot_date,
            start_time=s.start_time.strftime("%H:%M"),
            end_time=s.end_time.strftime("%H:%M"),
            is_booked=s.is_booked,
            max_bookings=s.max_bookings,
            current_bookings=s.current_bookings,
            available=s.current_bookings < s.max_bookings,
            created_at=s.created_at
        )
        for s in slots
    ]


@router.put("/slots/{slot_id}", response_model=CampaignAppointmentSlotOut)
def update_appointment_slot(
    slot_id: int,
    data: CampaignAppointmentSlotUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    slot = db.query(CampaignAppointmentSlot).filter(CampaignAppointmentSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    if data.slot_date:
        slot.slot_date = data.slot_date
    if data.start_time:
        slot.start_time = datetime.strptime(data.start_time, "%H:%M").time()
    if data.end_time:
        slot.end_time = datetime.strptime(data.end_time, "%H:%M").time()
    if data.max_bookings is not None:
        slot.max_bookings = data.max_bookings
    if data.is_booked is not None:
        slot.is_booked = data.is_booked
    slot.updated_at = ist_now()
    db.commit()
    db.refresh(slot)
    return CampaignAppointmentSlotOut(
        id=slot.id,
        campaign_id=slot.campaign_id,
        booking_link_id=slot.booking_link_id,
        slot_date=slot.slot_date,
        start_time=slot.start_time.strftime("%H:%M"),
        end_time=slot.end_time.strftime("%H:%M"),
        is_booked=slot.is_booked,
        max_bookings=slot.max_bookings,
        current_bookings=slot.current_bookings,
        available=slot.current_bookings < slot.max_bookings,
        created_at=slot.created_at
    )


@router.delete("/slots/{slot_id}")
def delete_appointment_slot(
    slot_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    slot = db.query(CampaignAppointmentSlot).filter(CampaignAppointmentSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    db.delete(slot)
    db.commit()
    return {"message": "Slot deleted successfully"}


@router.get("/book/{token}", response_model=CampaignBookingFormResponse)
def get_booking_form_data(
    token: str,
    db: Session = Depends(get_db)
):
    booking_link = db.query(CampaignBookingLink).filter(
        CampaignBookingLink.unique_token == token
    ).first()
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    if not booking_link.is_enabled:
        raise HTTPException(status_code=403, detail="Booking is currently disabled")
    campaign = db.query(Campaign).filter(Campaign.id == booking_link.campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    slots = db.query(CampaignAppointmentSlot).filter(
        and_(
            CampaignAppointmentSlot.booking_link_id == booking_link.id,
            CampaignAppointmentSlot.slot_date >= date.today(),
            CampaignAppointmentSlot.current_bookings < CampaignAppointmentSlot.max_bookings
        )
    ).order_by(CampaignAppointmentSlot.slot_date, CampaignAppointmentSlot.start_time).all()
    formatted_slots = [
        CampaignAppointmentSlotOut(
            id=s.id,
            campaign_id=s.campaign_id,
            booking_link_id=s.booking_link_id,
            slot_date=s.slot_date,
            start_time=s.start_time.strftime("%H:%M"),
            end_time=s.end_time.strftime("%H:%M"),
            is_booked=s.is_booked,
            max_bookings=s.max_bookings,
            current_bookings=s.current_bookings,
            available=s.current_bookings < s.max_bookings,
            created_at=s.created_at
        )
        for s in slots
    ]
    return CampaignBookingFormResponse(
        campaign_name=campaign.name or "",
        campaign_id=campaign.id,
        booking_link_id=booking_link.id,
        title=booking_link.page_title,
        logo_url=public_booking_logo_url(booking_link.logo_url),
        available_slots=formatted_slots,
        is_enabled=booking_link.is_enabled
    )


@router.post("/bookings", response_model=CampaignAppointmentBookingOut)
def create_booking(
    data: CampaignAppointmentBookingCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    slot, booking_date, start_t, end_t = _resolve_campaign_slot_for_booking(db, data)
    if slot.current_bookings >= slot.max_bookings:
        raise HTTPException(status_code=400, detail="Slot is fully booked")
    if slot.slot_date < date.today():
        raise HTTPException(status_code=400, detail="Cannot book past dates")
    booking = CampaignAppointmentBooking(
        slot_id=slot.id,
        campaign_id=slot.campaign_id,
        booking_date=booking_date,
        start_time=start_t,
        end_time=end_t,
        customer_name=data.customer_name,
        customer_email=data.customer_email,
        customer_phone=data.customer_phone,
        notes=data.notes,
        booking_status="Confirmed",
    )
    db.add(booking)
    slot.current_bookings += 1
    if slot.current_bookings >= slot.max_bookings:
        slot.is_booked = True
    db.commit()
    db.refresh(booking)
    background_tasks.add_task(send_campaign_appointment_confirmation_email, booking.id)
    return booking


@router.get("/bookings", response_model=List[CampaignAppointmentBookingOut])
def get_all_bookings(
    campaign_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    query = db.query(CampaignAppointmentBooking)
    if campaign_id:
        query = query.filter(CampaignAppointmentBooking.campaign_id == campaign_id)
    return query.order_by(CampaignAppointmentBooking.created_at.desc()).all()


@router.get("/bookings/campaign/{campaign_id}", response_model=List[CampaignAppointmentBookingOut])
def get_campaign_bookings(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return db.query(CampaignAppointmentBooking).filter(
        CampaignAppointmentBooking.campaign_id == campaign_id
    ).order_by(CampaignAppointmentBooking.created_at.desc()).all()


@router.post("/bookings/{booking_id}/send-email")
def manually_send_appointment_email(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    booking = db.query(CampaignAppointmentBooking).filter(CampaignAppointmentBooking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    original_setting = db.query(Settings).filter(Settings.key == "auto_appointment_email_enabled").first()
    original_value = original_setting.value if original_setting else None
    if original_setting and original_setting.value and original_setting.value.lower() == "false":
        original_setting.value = "true"
        db.commit()
    try:
        success = send_campaign_appointment_confirmation_email(booking_id)
    finally:
        if original_setting and original_value:
            original_setting.value = original_value
            db.commit()
    if success:
        return {"message": "Email sent successfully", "booking_id": booking_id}
    raise HTTPException(status_code=500, detail="Failed to send email.")


@router.get("/settings/appointment-email-template")
def get_appointment_email_template_id(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    setting = db.query(Settings).filter(Settings.key == "appointment_email_template_id").first()
    if not setting or not setting.value:
        return {"template_id": None, "message": "No appointment email template configured"}
    template = db.query(MessageTemplate).filter(MessageTemplate.id == int(setting.value)).first()
    if not template:
        return {"template_id": None, "message": "Template not found"}
    return {
        "template_id": int(setting.value),
        "template_name": template.name,
        "template_type": template.template_type,
        "status": template.status
    }


@router.post("/settings/set-appointment-email-template/{template_id}")
def set_appointment_email_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    template = db.query(MessageTemplate).filter(
        MessageTemplate.id == template_id,
        MessageTemplate.template_type == "email"
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Email template not found")
    setting = db.query(Settings).filter(Settings.key == "appointment_email_template_id").first()
    if setting:
        setting.value = str(template_id)
    else:
        setting = Settings(
            key="appointment_email_template_id",
            value=str(template_id),
            description="Email template ID for appointment confirmation emails"
        )
        db.add(setting)
    db.commit()
    return {"message": "Appointment email template set successfully", "template_id": template_id, "template_name": template.name}


@router.post("/settings/set-auto-appointment-email")
def set_auto_appointment_email(
    enabled: bool,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    setting = db.query(Settings).filter(Settings.key == "auto_appointment_email_enabled").first()
    if setting:
        setting.value = "true" if enabled else "false"
    else:
        setting = Settings(
            key="auto_appointment_email_enabled",
            value="true" if enabled else "false",
            description="Enable/disable automatic appointment confirmation emails"
        )
        db.add(setting)
    db.commit()
    return {"message": f"Automatic appointment emails {'enabled' if enabled else 'disabled'}", "enabled": enabled}


@router.get("/settings/auto-appointment-email-status")
def get_auto_appointment_email_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    setting = db.query(Settings).filter(Settings.key == "auto_appointment_email_enabled").first()
    if not setting or not setting.value:
        return {"enabled": True, "message": "Default: enabled"}
    return {"enabled": setting.value.lower() == "true"}
