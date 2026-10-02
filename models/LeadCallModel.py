from sqlalchemy import Column, ForeignKey, Integer, Text, DateTime, String, Boolean, Date
from database import Base
from utils.datetime_utils import ist_now
from sqlalchemy.orm import relationship

class LeadCall(Base):
    __tablename__ = "lead_calls"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    call_status = Column(String(50), nullable=False)  # Answered, No Answer, Busy, Voicemail, Failed, etc.
    call_duration = Column(Integer, nullable=True)  # Duration in seconds
    note = Column(Text, nullable=True)  # Call notes/transcript
    call_note_date = Column(Date, nullable=True)  # Optional structured date extracted by frontend
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    lead = relationship("Lead", back_populates="calls")

