from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from database import get_db
from models.ProjectModel import Project
from models.ProjectBookingModel import ProjectBookingLink, AppointmentSlot, AppointmentBooking
from models.MessageTemplateModel import MessageTemplate
from models.SettingsModel import Settings
from schemas.ProjectBookingSchema import (
    ProjectBookingLinkCreate, ProjectBookingLinkOut,
    AppointmentSlotCreate, AppointmentSlotUpdate, AppointmentSlotOut,
    AppointmentBookingCreate, AppointmentBookingOut, BookingFormResponse,
    BulkSlotCreate, BulkSlotCreateResponse, DayWiseSlot, TimeSlot, RecurringSlotCreate
)
from routers.auth import get_current_user
from routers.Notification import send_email
from typing import List, Optional
from datetime import datetime, date, time, timedelta
from utils.datetime_utils import ist_now, ist_today
import secrets
import re

router = APIRouter(prefix="/project-booking", tags=["Project Booking"])


def _parse_hhmm(s: str):
    return datetime.strptime(s.strip(), "%H:%M").time()


def _duration_minutes(start_t, end_t) -> int:
    a = datetime.combine(date.min, start_t)
    b = datetime.combine(date.min, end_t)
    return max(0, int((b - a).total_seconds() / 60))


def _resolve_project_slot_for_booking(db: Session, data: AppointmentBookingCreate):
    """
    Find the slot row that matches the user's chosen date and start/end times.
    slot_id may be wrong; matching is by project + booking_link + date + times.
    """
    hint = None
    if data.slot_id:
        hint = db.query(AppointmentSlot).filter(AppointmentSlot.id == data.slot_id).first()
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

    project_id = hint.project_id if hint else data.project_id
    booking_link_id = hint.booking_link_id if hint else data.booking_link_id
    if project_id is None or booking_link_id is None:
        raise HTTPException(
            status_code=400,
            detail="Provide slot_id or both project_id and booking_link_id with the booking date and times",
        )

    slot = (
        db.query(AppointmentSlot)
        .filter(
            AppointmentSlot.project_id == project_id,
            AppointmentSlot.booking_link_id == booking_link_id,
            AppointmentSlot.slot_date == booking_date,
            AppointmentSlot.start_time == start_t,
            AppointmentSlot.end_time == end_t,
        )
        .first()
    )
    if slot:
        return slot, booking_date, start_t, end_t

    link = (
        db.query(ProjectBookingLink)
        .filter(
            ProjectBookingLink.id == booking_link_id,
            ProjectBookingLink.project_id == project_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Booking link not found for this project")
    if not link.is_enabled:
        raise HTTPException(status_code=400, detail="Booking is disabled for this link")
    if booking_date < ist_today():
        raise HTTPException(status_code=400, detail="Cannot book past dates")
    if booking_date > ist_today() + timedelta(days=90):
        raise HTTPException(status_code=400, detail="Booking date is too far in the future")

    dur = _duration_minutes(start_t, end_t)
    slot = AppointmentSlot(
        project_id=project_id,
        booking_link_id=booking_link_id,
        slot_date=booking_date,
        start_time=start_t,
        end_time=end_t,
        is_booked=False,
        max_bookings=1,
        current_bookings=0,
    )
    db.add(slot)
    db.flush()

    return slot, booking_date, start_t, end_t


def replace_appointment_template_variables(content: str, appointment_data: dict) -> str:
    """Replace template variables with actual appointment data"""
    # Common variables that can be replaced
    replacements = {
        '{{name}}': appointment_data.get('customer_name', ''),
        '{{customer_name}}': appointment_data.get('customer_name', ''),
        '{{email}}': appointment_data.get('customer_email', ''),
        '{{customer_email}}': appointment_data.get('customer_email', ''),
        '{{phone}}': appointment_data.get('customer_phone', ''),
        '{{customer_phone}}': appointment_data.get('customer_phone', ''),
        '{{project_name}}': appointment_data.get('project_name', ''),
        '{{project_code}}': appointment_data.get('project_code', ''),
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
    
    # Also handle any other variables in the format {{variable_name}}
    def replace_var(match):
        var_name = match.group(1).lower()
        # Try to get from appointment_data, otherwise return empty string
        return str(appointment_data.get(var_name, ''))
    
    result = re.sub(r'\{\{(\w+)\}\}', replace_var, result)
    
    return result


def send_appointment_confirmation_email(booking_id: int):
    """Send appointment confirmation email using the configured template"""
    from database import SessionLocal
    
    db = SessionLocal()
    try:
        # Check if automatic appointment emails are enabled
        auto_email_setting = db.query(Settings).filter(Settings.key == "auto_appointment_email_enabled").first()
        if auto_email_setting and auto_email_setting.value and auto_email_setting.value.lower() == "false":
            print("ℹ️  Automatic appointment emails are disabled. Skipping email.")
            return False
        
        # Get booking with related data
        booking = db.query(AppointmentBooking).filter(AppointmentBooking.id == booking_id).first()
        if not booking:
            print(f"⚠️  Booking {booking_id} not found. Skipping email.")
            return False
        
        # Get slot and project information
        slot = db.query(AppointmentSlot).filter(AppointmentSlot.id == booking.slot_id).first()
        project = db.query(Project).filter(Project.id == booking.project_id).first()
        if not project:
            print(f"⚠️  Project for booking {booking_id} not found. Skipping email.")
            return False
        appt_date = booking.booking_date or (slot.slot_date if slot else None)
        appt_start = booking.start_time or (slot.start_time if slot else None)
        appt_end = booking.end_time or (slot.end_time if slot else None)
        if not appt_date or not appt_start:
            print(f"⚠️  No appointment date/time for booking {booking_id}. Skipping email.")
            return False
        
        # Get appointment email template ID from settings
        setting = db.query(Settings).filter(Settings.key == "appointment_email_template_id").first()
        
        if not setting or not setting.value:
            print("⚠️  No appointment email template configured. Skipping email.")
            print("   Set a template using: POST /project-booking/settings/set-appointment-email-template/{template_id}")
            return False
        
        template_id = int(setting.value)
        template = db.query(MessageTemplate).filter(
            MessageTemplate.id == template_id,
            MessageTemplate.template_type == "email",
            MessageTemplate.status == "Active"
        ).first()
        
        if not template:
            print(f"⚠️  Template {template_id} not found or not active. Skipping email.")
            return False
        
        # Prepare appointment data for variable replacement
        appointment_data = {
            'customer_name': booking.customer_name,
            'customer_email': booking.customer_email,
            'customer_phone': booking.customer_phone or '',
            'project_name': project.project_name,
            'project_code': project.project_code or '',
            'slot_date': appt_date.strftime('%Y-%m-%d'),
            'start_time': appt_start.strftime('%H:%M'),
            'end_time': appt_end.strftime('%H:%M') if appt_end else '',
            'booking_status': booking.booking_status,
            'notes': booking.notes or '',
            'booking_date': booking.created_at.strftime('%Y-%m-%d') if booking.created_at else '',
            'booking_time': booking.created_at.strftime('%H:%M:%S') if booking.created_at else '',
            'booking_id': booking.id,
        }
        
        # Replace variables in subject and content
        subject = replace_appointment_template_variables(template.subject or "Appointment Confirmation", appointment_data)
        content = replace_appointment_template_variables(template.content, appointment_data)
        
        # Send email
        success, _ = send_email(booking.customer_email, subject, content)
        
        # Track template usage (track attempts even if failed)
        template.usage_count += 1
        if success:
            template.success_count += 1
        if template.usage_count > 0:
            template.success_rate = (template.success_count / template.usage_count) * 100
        db.commit()
        
        if not success:
            print(f"⚠️  Appointment confirmation email failed for booking {booking_id} ({booking.customer_email}), but booking was created successfully.")
        
        return success
        
    except Exception as e:
        print(f"✗ Error sending appointment confirmation email: {e}")
        print(f"   Booking {booking_id} was created successfully, but email could not be sent.")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def generate_unique_token() -> str:
    """Generate a unique token for booking link"""
    return secrets.token_urlsafe(32)


def get_base_url(request: Request) -> str:
    """Get base URL from request"""
    scheme = request.url.scheme
    host = request.url.hostname
    port = request.url.port
    if port and port not in [80, 443]:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


# Generate or get booking link for a project
@router.post("/generate-link", response_model=ProjectBookingLinkOut)
def generate_booking_link(
    data: ProjectBookingLinkCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Generate a unique booking link for a project"""
    # Check if project exists
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check if booking link already exists
    existing_link = db.query(ProjectBookingLink).filter(
        ProjectBookingLink.project_id == data.project_id
    ).first()
    
    if existing_link:
        # Update existing link
        existing_link.is_enabled = data.is_enabled
        existing_link.updated_at = ist_now()
        db.commit()
        db.refresh(existing_link)
        return existing_link
    
    # Generate new token
    token = generate_unique_token()
    base_url = get_base_url(request)
    booking_url = f"{base_url}/project-booking/book/{token}"
    
    # Create new booking link
    booking_link = ProjectBookingLink(
        project_id=data.project_id,
        unique_token=token,
        booking_url=booking_url,
        is_enabled=data.is_enabled
    )
    
    db.add(booking_link)
    db.commit()
    db.refresh(booking_link)
    
    return booking_link


# Get booking link for a project
@router.get("/link/{project_id}", response_model=ProjectBookingLinkOut)
def get_booking_link(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Get booking link for a project"""
    booking_link = db.query(ProjectBookingLink).filter(
        ProjectBookingLink.project_id == project_id
    ).first()
    
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found for this project")
    
    # Update URL if needed
    base_url = get_base_url(request)
    booking_link.booking_url = f"{base_url}/project-booking/book/{booking_link.unique_token}"
    db.commit()
    db.refresh(booking_link)
    
    return booking_link


# Get all booking links
@router.get("/all-links", response_model=List[ProjectBookingLinkOut])
def get_all_booking_links(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Get all booking links"""
    links = db.query(ProjectBookingLink).all()
    
    # Update URLs
    base_url = get_base_url(request)
    for link in links:
        link.booking_url = f"{base_url}/project-booking/book/{link.unique_token}"
    
    db.commit()
    return links


# Update booking link
@router.put("/link/{link_id}", response_model=ProjectBookingLinkOut)
def update_booking_link(
    link_id: int,
    is_enabled: bool,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Update booking link status"""
    booking_link = db.query(ProjectBookingLink).filter(ProjectBookingLink.id == link_id).first()
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    
    booking_link.is_enabled = is_enabled
    booking_link.updated_at = ist_now()
    db.commit()
    db.refresh(booking_link)
    
    return booking_link


# Add appointment slots
@router.post("/slots", response_model=AppointmentSlotOut)
def create_appointment_slot(
    data: AppointmentSlotCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Create appointment slots for a project"""
    # Validate project and booking link
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    booking_link = db.query(ProjectBookingLink).filter(
        ProjectBookingLink.id == data.booking_link_id
    ).first()
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    
    if booking_link.project_id != data.project_id:
        raise HTTPException(status_code=400, detail="Booking link does not belong to this project")
    
    # Parse time strings
    try:
        start_time_obj = datetime.strptime(data.start_time, "%H:%M").time()
        end_time_obj = datetime.strptime(data.end_time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM format")
    
    if end_time_obj <= start_time_obj:
        raise HTTPException(status_code=400, detail="End time must be after start time")
    
    # Check if slot already exists
    existing_slot = db.query(AppointmentSlot).filter(
        and_(
            AppointmentSlot.project_id == data.project_id,
            AppointmentSlot.slot_date == data.slot_date,
            AppointmentSlot.start_time == start_time_obj,
            AppointmentSlot.end_time == end_time_obj
        )
    ).first()
    
    if existing_slot:
        raise HTTPException(status_code=400, detail="Slot already exists for this date and time")
    
    # Create slot
    slot = AppointmentSlot(
        project_id=data.project_id,
        booking_link_id=data.booking_link_id,
        slot_date=data.slot_date,
        start_time=start_time_obj,
        end_time=end_time_obj,
        max_bookings=data.max_bookings
    )
    
    db.add(slot)
    db.commit()
    db.refresh(slot)
    
    # Format response
    slot_out = AppointmentSlotOut(
        id=slot.id,
        project_id=slot.project_id,
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
    
    return slot_out


# Create recurring appointment slots (by day of week)
@router.post("/slots/recurring", response_model=BulkSlotCreateResponse)
def create_recurring_slots(
    data: RecurringSlotCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Create recurring appointment slots based on days of week (Monday, Tuesday, etc.)"""
    # Validate project and booking link
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    booking_link = db.query(ProjectBookingLink).filter(
        ProjectBookingLink.id == data.booking_link_id
    ).first()
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    
    if booking_link.project_id != data.project_id:
        raise HTTPException(status_code=400, detail="Booking link does not belong to this project")
    
    # Validate date range
    if data.end_date < data.start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")
    
    if data.start_date < ist_today():
        raise HTTPException(status_code=400, detail="Start date cannot be in the past")
    
    # Validate days of week (0=Monday, 6=Sunday)
    for day in data.days_of_week:
        if day < 0 or day > 6:
            raise HTTPException(status_code=400, detail=f"Invalid day of week: {day}. Must be 0-6 (0=Monday, 6=Sunday)")
    
    if not data.days_of_week:
        raise HTTPException(status_code=400, detail="At least one day of week must be selected")
    
    if not data.time_slots:
        raise HTTPException(status_code=400, detail="At least one time slot must be provided")
    
    created_slots = []
    skipped_count = 0
    errors = []
    
    # Generate all dates for selected days of week in the date range
    current_date = data.start_date
    matching_dates = []
    
    while current_date <= data.end_date:
        # weekday() returns 0=Monday, 1=Tuesday, ..., 6=Sunday
        if current_date.weekday() in data.days_of_week:
            matching_dates.append(current_date)
        current_date += timedelta(days=1)
    
    # Create slots for each matching date with all time slots
    for slot_date in matching_dates:
        for time_slot in data.time_slots:
            try:
                # Parse time strings
                try:
                    start_time_obj = datetime.strptime(time_slot.start_time, "%H:%M").time()
                    end_time_obj = datetime.strptime(time_slot.end_time, "%H:%M").time()
                except ValueError:
                    errors.append(f"Invalid time format for {slot_date}: {time_slot.start_time}-{time_slot.end_time}. Use HH:MM format.")
                    skipped_count += 1
                    continue
                
                if end_time_obj <= start_time_obj:
                    errors.append(f"End time must be after start time for {slot_date}: {time_slot.start_time}-{time_slot.end_time}")
                    skipped_count += 1
                    continue
                
                # Check if slot already exists
                existing_slot = db.query(AppointmentSlot).filter(
                    and_(
                        AppointmentSlot.project_id == data.project_id,
                        AppointmentSlot.slot_date == slot_date,
                        AppointmentSlot.start_time == start_time_obj,
                        AppointmentSlot.end_time == end_time_obj
                    )
                ).first()
                
                if existing_slot:
                    errors.append(f"Slot already exists for {slot_date} at {time_slot.start_time}-{time_slot.end_time}")
                    skipped_count += 1
                    continue
                
                # Create slot
                slot = AppointmentSlot(
                    project_id=data.project_id,
                    booking_link_id=data.booking_link_id,
                    slot_date=slot_date,
                    start_time=start_time_obj,
                    end_time=end_time_obj,
                    max_bookings=time_slot.max_bookings
                )
                
                db.add(slot)
                db.flush()  # Flush to get the ID without committing
                
                # Format for response
                slot_out = AppointmentSlotOut(
                    id=slot.id,
                    project_id=slot.project_id,
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
                created_slots.append(slot_out)
                
            except Exception as e:
                errors.append(f"Error creating slot for {slot_date} at {time_slot.start_time}-{time_slot.end_time}: {str(e)}")
                skipped_count += 1
                continue
    
    # Commit all created slots at once
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error committing slots: {str(e)}")
    
    return BulkSlotCreateResponse(
        created_count=len(created_slots),
        skipped_count=skipped_count,
        errors=errors,
        created_slots=created_slots
    )


# Bulk create appointment slots (day-wise)
@router.post("/slots/bulk", response_model=BulkSlotCreateResponse)
def bulk_create_appointment_slots(
    data: BulkSlotCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Create multiple appointment slots day-wise in a single request"""
    # Validate project and booking link
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    booking_link = db.query(ProjectBookingLink).filter(
        ProjectBookingLink.id == data.booking_link_id
    ).first()
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    
    if booking_link.project_id != data.project_id:
        raise HTTPException(status_code=400, detail="Booking link does not belong to this project")
    
    created_slots = []
    skipped_count = 0
    errors = []
    
    # Process each day's slots
    for day_slot in data.day_wise_slots:
        # Validate date is not in the past
        if day_slot.slot_date < ist_today():
            errors.append(f"Date {day_slot.slot_date} is in the past. Skipping all slots for this date.")
            skipped_count += len(day_slot.time_slots)
            continue
        
        # Process each time slot for this day
        for time_slot in day_slot.time_slots:
            try:
                # Parse time strings
                try:
                    start_time_obj = datetime.strptime(time_slot.start_time, "%H:%M").time()
                    end_time_obj = datetime.strptime(time_slot.end_time, "%H:%M").time()
                except ValueError:
                    errors.append(f"Invalid time format for {day_slot.slot_date}: {time_slot.start_time}-{time_slot.end_time}. Use HH:MM format.")
                    skipped_count += 1
                    continue
                
                if end_time_obj <= start_time_obj:
                    errors.append(f"End time must be after start time for {day_slot.slot_date}: {time_slot.start_time}-{time_slot.end_time}")
                    skipped_count += 1
                    continue
                
                # Check if slot already exists
                existing_slot = db.query(AppointmentSlot).filter(
                    and_(
                        AppointmentSlot.project_id == data.project_id,
                        AppointmentSlot.slot_date == day_slot.slot_date,
                        AppointmentSlot.start_time == start_time_obj,
                        AppointmentSlot.end_time == end_time_obj
                    )
                ).first()
                
                if existing_slot:
                    errors.append(f"Slot already exists for {day_slot.slot_date} at {time_slot.start_time}-{time_slot.end_time}")
                    skipped_count += 1
                    continue
                
                # Create slot
                slot = AppointmentSlot(
                    project_id=data.project_id,
                    booking_link_id=data.booking_link_id,
                    slot_date=day_slot.slot_date,
                    start_time=start_time_obj,
                    end_time=end_time_obj,
                    max_bookings=time_slot.max_bookings
                )
                
                db.add(slot)
                db.flush()  # Flush to get the ID without committing
                
                # Format for response
                slot_out = AppointmentSlotOut(
                    id=slot.id,
                    project_id=slot.project_id,
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
                created_slots.append(slot_out)
                
            except Exception as e:
                errors.append(f"Error creating slot for {day_slot.slot_date} at {time_slot.start_time}-{time_slot.end_time}: {str(e)}")
                skipped_count += 1
                continue
    
    # Commit all created slots at once
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error committing slots: {str(e)}")
    
    return BulkSlotCreateResponse(
        created_count=len(created_slots),
        skipped_count=skipped_count,
        errors=errors,
        created_slots=created_slots
    )


# Get slots for a project
@router.get("/slots/{project_id}", response_model=List[AppointmentSlotOut])
def get_appointment_slots(
    project_id: int,
    slot_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Get appointment slots for a project"""
    query = db.query(AppointmentSlot).filter(AppointmentSlot.project_id == project_id)
    
    if slot_date:
        query = query.filter(AppointmentSlot.slot_date == slot_date)
    else:
        # Get slots from today onwards
        query = query.filter(AppointmentSlot.slot_date >= ist_today())
    
    slots = query.order_by(AppointmentSlot.slot_date, AppointmentSlot.start_time).all()
    
    result = []
    for slot in slots:
        result.append(AppointmentSlotOut(
            id=slot.id,
            project_id=slot.project_id,
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
    
    return result


# Update slot
@router.put("/slots/{slot_id}", response_model=AppointmentSlotOut)
def update_appointment_slot(
    slot_id: int,
    data: AppointmentSlotUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Update an appointment slot"""
    slot = db.query(AppointmentSlot).filter(AppointmentSlot.id == slot_id).first()
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
    
    return AppointmentSlotOut(
        id=slot.id,
        project_id=slot.project_id,
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


# Delete slot
@router.delete("/slots/{slot_id}")
def delete_appointment_slot(
    slot_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Delete an appointment slot"""
    slot = db.query(AppointmentSlot).filter(AppointmentSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    
    db.delete(slot)
    db.commit()
    
    return {"message": "Slot deleted successfully"}


# Public endpoint - Get booking form data (for frontend)
@router.get("/book/{token}", response_model=BookingFormResponse)
def get_booking_form_data(
    token: str,
    db: Session = Depends(get_db)
):
    """Public endpoint to get booking form data (returns JSON for frontend integration)"""
    # Get booking link
    booking_link = db.query(ProjectBookingLink).filter(
        ProjectBookingLink.unique_token == token
    ).first()
    
    if not booking_link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    
    if not booking_link.is_enabled:
        raise HTTPException(status_code=403, detail="Booking is currently disabled")
    
    # Get project
    project = db.query(Project).filter(Project.id == booking_link.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get available slots (from today onwards)
    slots = db.query(AppointmentSlot).filter(
        and_(
            AppointmentSlot.booking_link_id == booking_link.id,
            AppointmentSlot.slot_date >= ist_today(),
            AppointmentSlot.current_bookings < AppointmentSlot.max_bookings
        )
    ).order_by(AppointmentSlot.slot_date, AppointmentSlot.start_time).all()
    
    # Format slots for response
    formatted_slots = []
    for slot in slots:
        formatted_slots.append(AppointmentSlotOut(
            id=slot.id,
            project_id=slot.project_id,
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
    
    return BookingFormResponse(
        project_name=project.project_name,
        project_code=project.project_code,
        booking_link_id=booking_link.id,
        available_slots=formatted_slots,
        is_enabled=booking_link.is_enabled
    )


# Submit booking (public endpoint)
@router.post("/bookings", response_model=AppointmentBookingOut)
def create_booking(
    data: AppointmentBookingCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Submit a booking (public endpoint)"""
    slot, booking_date, start_t, end_t = _resolve_project_slot_for_booking(db, data)

    if slot.current_bookings >= slot.max_bookings:
        raise HTTPException(status_code=400, detail="Slot is fully booked")

    if slot.slot_date < ist_today():
        raise HTTPException(status_code=400, detail="Cannot book past dates")

    booking = AppointmentBooking(
        slot_id=slot.id,
        project_id=slot.project_id,
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

    background_tasks.add_task(send_appointment_confirmation_email, booking.id)

    return booking


# Get all bookings (admin endpoint)
@router.get("/bookings", response_model=List[AppointmentBookingOut])
def get_all_bookings(
    project_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Get all bookings (admin only)"""
    query = db.query(AppointmentBooking)
    
    if project_id:
        query = query.filter(AppointmentBooking.project_id == project_id)
    
    bookings = query.order_by(AppointmentBooking.created_at.desc()).all()
    return bookings


# Get bookings for a project
@router.get("/bookings/project/{project_id}", response_model=List[AppointmentBookingOut])
def get_project_bookings(
    project_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Get all bookings for a specific project"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    bookings = db.query(AppointmentBooking).filter(
        AppointmentBooking.project_id == project_id
    ).order_by(AppointmentBooking.created_at.desc()).all()
    
    return bookings


# Manually send appointment confirmation email
@router.post("/bookings/{booking_id}/send-email")
def manually_send_appointment_email(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Manually send appointment confirmation email for a booking"""
    booking = db.query(AppointmentBooking).filter(AppointmentBooking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Temporarily enable auto email for manual sending
    original_setting = db.query(Settings).filter(Settings.key == "auto_appointment_email_enabled").first()
    original_value = original_setting.value if original_setting else None
    
    # Temporarily enable if disabled
    if original_setting and original_setting.value and original_setting.value.lower() == "false":
        original_setting.value = "true"
        db.commit()
    
    try:
        # Send email (bypasses auto_enabled check for manual sending)
        success = send_appointment_confirmation_email(booking_id)
    finally:
        # Restore original setting
        if original_setting and original_value:
            original_setting.value = original_value
            db.commit()
    
    if success:
        return {"message": "Email sent successfully", "booking_id": booking_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to send email. Check server logs for details.")


# Settings endpoints for appointment email template
@router.get("/settings/appointment-email-template")
def get_appointment_email_template_id(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Get the appointment email template ID from settings"""
    setting = db.query(Settings).filter(Settings.key == "appointment_email_template_id").first()
    
    if not setting or not setting.value:
        return {"template_id": None, "message": "No appointment email template configured"}
    
    # Verify template exists
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
    """Set the appointment email template ID in settings"""
    # Verify template exists and is an email template
    template = db.query(MessageTemplate).filter(
        MessageTemplate.id == template_id,
        MessageTemplate.template_type == "email"
    ).first()
    
    if not template:
        raise HTTPException(status_code=404, detail="Email template not found")
    
    # Get or create setting
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
    
    return {
        "message": "Appointment email template set successfully",
        "template_id": template_id,
        "template_name": template.name
    }


@router.post("/settings/set-auto-appointment-email")
def set_auto_appointment_email(
    enabled: bool,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Enable or disable automatic appointment confirmation emails"""
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
    
    return {
        "message": f"Automatic appointment emails {'enabled' if enabled else 'disabled'}",
        "enabled": enabled
    }


@router.get("/settings/auto-appointment-email-status")
def get_auto_appointment_email_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Get the status of automatic appointment emails"""
    setting = db.query(Settings).filter(Settings.key == "auto_appointment_email_enabled").first()
    
    if not setting or not setting.value:
        return {"enabled": True, "message": "Default: enabled (setting not configured)"}
    
    enabled = setting.value.lower() == "true"
    return {"enabled": enabled}

