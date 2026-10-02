"""
Reminder model: user-set reminders with frequency (daily, weekly, monthly, once)
and optional date/time. Can be assigned to one or more users.
"""
from sqlalchemy import Column, Integer, String, Text, Date, Time, DateTime, ForeignKey, Boolean, Table
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now


reminder_user_association = Table(
    "reminder_user_association",
    Base.metadata,
    Column("reminder_id", Integer, ForeignKey("reminders.id")),
    Column("user_id", Integer, ForeignKey("users.id")),
)


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    # Legacy owner field; kept in sync with the first assignee for backward compatibility.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    title = Column(String(500), nullable=False)
    notes = Column(Text, nullable=True)

    # frequency: daily | weekly | monthly | once
    frequency = Column(String(20), nullable=False, default="once")

    # For "once": the exact date. For weekly/monthly can store next occurrence or config.
    reminder_date = Column(Date, nullable=True)
    # Time of day (HH:MM) - used for daily, weekly, monthly, and once
    reminder_time = Column(Time, nullable=True)

    # For weekly: 1=Monday .. 7=Sunday (ISO weekday)
    day_of_week = Column(Integer, nullable=True)
    # For monthly: 1-31 (day of month)
    day_of_month = Column(Integer, nullable=True)

    group_id = Column(Integer, ForeignKey("reminder_groups.id", ondelete="CASCADE"), nullable=True, index=True)
    sort_order = Column(Integer, nullable=False, default=0)
    use_custom_schedule = Column(Boolean, default=False, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)

    user = relationship("User", foreign_keys=[user_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    group = relationship("ReminderGroup", back_populates="reminders")
    assigned_users = relationship(
        "User",
        secondary=reminder_user_association,
        back_populates="assigned_reminders",
    )
    snoozes = relationship("ReminderSnooze", back_populates="reminder", cascade="all, delete-orphan")
