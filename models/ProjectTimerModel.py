from sqlalchemy import Column, DateTime, Integer, Float, ForeignKey, String, Date, Text
from database import Base
from sqlalchemy.orm import relationship

class ProjectTimer(Base):
    __tablename__ = "project_timers"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    employee_username = Column(String(255), nullable=False)
    start_time = Column(String(255), nullable=False)
    end_time = Column(String(255), nullable=True)
    date = Column(Date, nullable=False)
    notes = Column(Text, nullable=True)

    project = relationship("Project", back_populates="timers")