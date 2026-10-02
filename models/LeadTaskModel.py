from sqlalchemy import Column, ForeignKey, Integer, String, Date, Boolean, DateTime
from database import Base
from utils.datetime_utils import ist_now
from sqlalchemy.orm import relationship

class LeadTask(Base):
    __tablename__ = "lead_tasks"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    title = Column(String(200), nullable=False)
    due_date = Column(Date, nullable=True)
    assigned_to = Column(Integer, ForeignKey("users.id"))
    completed = Column(Boolean, default=False)
    created_by = Column(String(100))
    created_at = Column(DateTime(timezone=True), default=ist_now)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    lead = relationship("Lead", back_populates="tasks")
