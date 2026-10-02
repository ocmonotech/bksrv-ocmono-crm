from sqlalchemy import Column, ForeignKey, Integer, Text, DateTime, String, Boolean
from database import Base
from utils.datetime_utils import ist_now
from sqlalchemy.orm import relationship

class LeadNote(Base):
    __tablename__ = "lead_notes"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    content = Column(Text)
    created_by = Column(String(100))
    created_at = Column(DateTime(timezone=True), default=ist_now)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    lead = relationship("Lead", back_populates="notes")
