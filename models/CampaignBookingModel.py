from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Date, Time
from database import Base
from sqlalchemy.orm import relationship
from utils.datetime_utils import ist_now


class CampaignBookingLink(Base):
    __tablename__ = "campaign_booking_links"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    unique_token = Column(String(100), unique=True, nullable=False, index=True)
    booking_url = Column(String(500))
    # Optional branding for the public booking page (JSON field name: "title")
    page_title = Column(String(255), nullable=True)
    logo_url = Column(String(512), nullable=True)
    is_enabled = Column(Boolean, default=True)
    # Booking window: min hours in advance to book; slots within this window cannot be booked
    min_hours_advance = Column(Integer, default=2)
    # Max days ahead customers can book (e.g. 30 = book up to 30 days in advance)
    max_days_ahead = Column(Integer, default=30)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)

    campaign = relationship("Campaign", back_populates="booking_links")
    slots = relationship("CampaignAppointmentSlot", back_populates="booking_link", cascade="all, delete-orphan")
    recurring_schedules = relationship(
        "CampaignRecurringSchedule",
        back_populates="booking_link",
        cascade="all, delete-orphan",
    )


class CampaignRecurringSchedule(Base):
    """Template for recurring slots by weekday. Slots are generated for each occurrence in the booking window."""
    __tablename__ = "campaign_recurring_schedules"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    booking_link_id = Column(Integer, ForeignKey("campaign_booking_links.id"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    duration_minutes = Column(Integer, default=30)
    max_bookings = Column(Integer, default=1)  # persons per slot
    sort_order = Column(Integer, default=0)

    campaign = relationship("Campaign")
    booking_link = relationship("CampaignBookingLink", back_populates="recurring_schedules")


class CampaignAppointmentSlot(Base):
    __tablename__ = "campaign_appointment_slots"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    booking_link_id = Column(Integer, ForeignKey("campaign_booking_links.id"), nullable=False)
    slot_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    duration_minutes = Column(Integer, nullable=True)  # optional; can be derived from start/end
    is_booked = Column(Boolean, default=False)
    max_bookings = Column(Integer, default=1)
    current_bookings = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)

    campaign = relationship("Campaign")
    booking_link = relationship("CampaignBookingLink", back_populates="slots")
    bookings = relationship("CampaignAppointmentBooking", back_populates="slot", cascade="all, delete-orphan")


class CampaignAppointmentBooking(Base):
    __tablename__ = "campaign_appointment_bookings"

    id = Column(Integer, primary_key=True, index=True)
    slot_id = Column(Integer, ForeignKey("campaign_appointment_slots.id"), nullable=False)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    # Actual appointment window chosen by the user (source of truth for display)
    booking_date = Column(Date, nullable=True)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    customer_name = Column(String(200), nullable=False)
    customer_email = Column(String(200), nullable=False)
    customer_phone = Column(String(50))
    notes = Column(Text)
    booking_status = Column(String(50), default="Confirmed")  # Confirmed, Cancelled, Completed
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)

    slot = relationship("CampaignAppointmentSlot", back_populates="bookings")
    campaign = relationship("Campaign")
