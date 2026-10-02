"""
Task model for assignment-scoped tasks (Clients > Projects > Assignments > Tasks).
Each task belongs to one assignment and can have multiple assignees.
"""
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, Date, ForeignKey, Boolean, Table
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now

task_user_association = Table(
    "task_user_association",
    Base.metadata,
    Column("task_id", Integer, ForeignKey("tasks.id")),
    Column("user_id", Integer, ForeignKey("users.id")),
)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=True)

    due_date = Column(Date, nullable=True)
    priority = Column(String(50), default="Normal")  # Normal, High, Medium, Low
    status = Column(String(50), default="Pending")  # Pending, In Progress, Completed, On Hold, Cancelled

    estimated_hours = Column(Float, default=0)
    actual_hours = Column(Float, default=0)

    brief_link = Column(Text, nullable=True)
    resources_link = Column(Text, nullable=True)
    client_folder_link = Column(Text, nullable=True)
    work_link = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)

    client = relationship("Client", foreign_keys=[client_id])
    project = relationship("Project", foreign_keys=[project_id])
    assignment = relationship("Assignment", foreign_keys=[assignment_id])
    assigned_users = relationship(
        "User",
        secondary=task_user_association,
        back_populates="assigned_tasks",
    )
