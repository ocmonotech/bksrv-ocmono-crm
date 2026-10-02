"""
Todo model: title, due date/time, priority, list, notes, multiple assignees,
recurrence (daily/weekly/monthly), reminder_days_before for weekly/monthly.
"""
from sqlalchemy import Column, Integer, String, Text, Date, Time, DateTime, ForeignKey, Boolean, Table
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now

todo_user_association = Table(
    "todo_user_association",
    Base.metadata,
    Column("todo_id", Integer, ForeignKey("todos.id")),
    Column("user_id", Integer, ForeignKey("users.id")),
)


class Todo(Base):
    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    due_date = Column(Date, nullable=True)
    due_time = Column(Time, nullable=True)
    priority = Column(String(50), default="Normal")  # Normal, High, Medium, Low
    list_name = Column(String(100), default="Default")
    notes = Column(Text, nullable=True)
    # is_completed = Column(Boolean, default=False)

    # Recurrence: one_time, daily, weekly, monthly
    recurrence_interval = Column(String(20), default="none")
    # For weekly/monthly: how many days before due to send reminder (e.g. 2 = 2 days before)
    reminder_days_before = Column(Integer, nullable=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)
    completed_at = Column(DateTime(timezone=True), nullable=True, onupdate=ist_now)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    created_by = relationship("User", foreign_keys=[created_by_id])
    assigned_users = relationship(
        "User",
        secondary=todo_user_association,
        back_populates="assigned_todos",
    )
