from sqlalchemy import Column, ForeignKey, Integer, Text, DateTime, String
from database import Base
from utils.datetime_utils import ist_now
from sqlalchemy.orm import relationship

class LeadWhatsApp(Base):
    __tablename__ = "lead_whatsapp"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    message_type = Column(String(50), nullable=False)  # sent, received
    message_content = Column(Text, nullable=False)
    status = Column(String(50), nullable=True)  # sent, delivered, read, failed
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), default=ist_now)

    lead = relationship("Lead", back_populates="whatsapp_messages")

