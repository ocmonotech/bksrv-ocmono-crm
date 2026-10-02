"""Reminder groups: shared schedule, notes, assignees, and multiple reminder items."""
from sqlalchemy import Column, Integer, String, Text, Date, Time, DateTime, ForeignKey, Boolean, Table
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now


reminder_group_user_association = Table(
    "reminder_group_user_association",
    Base.metadata,
    Column("reminder_group_id", Integer, ForeignKey("reminder_groups.id")),
    Column("user_id", Integer, ForeignKey("users.id")),
)


class ReminderGroup(Base):
    __tablename__ = "reminder_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(500), nullable=False)
    notes = Column(Text, nullable=True)

    frequency = Column(String(20), nullable=False, default="once")
    reminder_date = Column(Date, nullable=True)
    reminder_time = Column(Time, nullable=True)
    day_of_week = Column(Integer, nullable=True)
    day_of_month = Column(Integer, nullable=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)

    created_by = relationship("User", foreign_keys=[created_by_id])
    assigned_users = relationship(
        "User",
        secondary=reminder_group_user_association,
        back_populates="assigned_reminder_groups",
    )
    reminders = relationship(
        "Reminder",
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="Reminder.sort_order",
    )
