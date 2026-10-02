from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Table, Float, Boolean
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now


assignment_user_association = Table(
    "assignment_user_association",
    Base.metadata,
    Column("assignment_id", Integer, ForeignKey("assignments.id")),
    Column("user_id", Integer, ForeignKey("users.id"))
)


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    assignment_code = Column(String(100), unique=True, nullable=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="Pending")
    created_by = Column(String(100))
    assigned_to = Column(String(100), nullable=True)
    due_date = Column(DateTime, nullable=True)
    assigned_by = Column(String(100), nullable=True)
    priority = Column(String(50), default="Normal")
    completed_at = Column(String(500), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    estimated_hours = Column(Float, default=0)
    actual_hours = Column(Float, default=0)
    brief_link = Column(Text, nullable=True)
    resources_link = Column(Text, nullable=True)
    client_folder_link = Column(Text, nullable=True)
    work_link = Column(Text, nullable=True)
    updated_by = Column(String(100), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True, default=ist_now)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    assigned_group_id = Column(Integer, ForeignKey("user_groups.id"), nullable=True)
    assigned_group_name = Column(String(150), nullable=True)

    assigned_users = relationship("User", secondary=assignment_user_association, back_populates="assigned_assignments")
    assigned_group = relationship("UserGroup", foreign_keys=[assigned_group_id])
    client = relationship("Client", foreign_keys=[client_id])
    project = relationship("Project", foreign_keys=[project_id])
