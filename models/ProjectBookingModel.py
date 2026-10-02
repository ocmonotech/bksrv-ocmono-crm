from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Date, Time
from database import Base
from sqlalchemy.orm import relationship
from utils.datetime_utils import ist_now

class ProjectBookingLink(Base):
    __tablename__ = "project_booking_links"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    unique_token = Column(String(100), unique=True, nullable=False, index=True)
    booking_url = Column(String(500))
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)

    project = relationship("Project", back_populates="booking_links")
    slots = relationship("AppointmentSlot", back_populates="booking_link", cascade="all, delete-orphan")


class AppointmentSlot(Base):
    __tablename__ = "appointment_slots"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    booking_link_id = Column(Integer, ForeignKey("project_booking_links.id"), nullable=False)
    slot_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_booked = Column(Boolean, default=False)
    max_bookings = Column(Integer, default=1)  # Allow multiple bookings per slot if needed
    current_bookings = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)

    project = relationship("Project")
    booking_link = relationship("ProjectBookingLink", back_populates="slots")
    bookings = relationship("AppointmentBooking", back_populates="slot", cascade="all, delete-orphan")


class AppointmentBooking(Base):
    __tablename__ = "appointment_bookings"

    id = Column(Integer, primary_key=True, index=True)
    slot_id = Column(Integer, ForeignKey("appointment_slots.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    # Actual appointment window chosen by the user (source of truth for display; may differ from slot row if slot_id was wrong)
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

    slot = relationship("AppointmentSlot", back_populates="bookings")
    project = relationship("Project")

