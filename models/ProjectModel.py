from sqlalchemy import Column, Integer, String, Text, Float, ForeignKey, Boolean, DateTime
from database import Base
from sqlalchemy.orm import relationship

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    project_code = Column(String(50), unique=True)
    project_name = Column(String(100), nullable=False)
    project_client = Column(String(100))  # client_name
    project_type_name = Column(String(100))  # type_name
    assigned_persons = Column(Text)  # comma-separated usernames
    project_status = Column(String(50), nullable=False)
    project_note = Column(Text)
    total_time_spent = Column(Integer, default=0)  # Total time in seconds
    client_id = Column(Integer, ForeignKey("clients.id"))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    timers = relationship("ProjectTimer", back_populates="project", cascade="all, delete-orphan")
    client = relationship("Client", back_populates="projects")
    subtasks = relationship("ProjectSubtask", back_populates="project", cascade="all, delete")
    booking_links = relationship("ProjectBookingLink", back_populates="project", cascade="all, delete-orphan")
