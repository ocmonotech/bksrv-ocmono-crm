"""Per-user snooze state for reminders."""
from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now


class ReminderSnooze(Base):
    __tablename__ = "reminder_snoozes"
    __table_args__ = (
        UniqueConstraint("reminder_id", "user_id", name="uq_reminder_snooze_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    reminder_id = Column(Integer, ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    snoozed_until = Column(DateTime(timezone=True), nullable=False)
    snoozed_at = Column(DateTime(timezone=True), default=ist_now, nullable=False)

    reminder = relationship("Reminder", back_populates="snoozes")
    user = relationship("User", foreign_keys=[user_id])
