from sqlalchemy import Column, Date, Float, ForeignKey, Integer, String, DateTime, JSON, Boolean
from database import Base
from sqlalchemy.orm import relationship

class LeadAssignment(Base):
    __tablename__ = "lead_assignments"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    user_id = Column(Integer, ForeignKey("users.id"))

    lead = relationship("Lead", back_populates="assigned_users")
    user = relationship("User") 


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True)
    phone = Column(String(15),nullable=True)
    status = Column(String(50),nullable=True, default="New")  # New, Contacted, Qualified
    priority = Column(String(50),nullable=True, default="low")  # Low, Medium, High
    date_created = Column(DateTime)
    date_updated = Column(DateTime, nullable=True)
    lead_date = Column(DateTime, nullable=True)
    created_by = Column(String(100))
    created_at = Column(DateTime, nullable=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"))
    tags = Column(JSON, nullable=True)
    call_count = Column(Integer, default=0)
    whatsapp_count = Column(Integer, default=0)
    sheets_lead_id = Column(String(100), nullable=True)
    ad_name = Column(String(200), nullable=True)
    platform = Column(String(100), nullable=True)
    what_best_describes_your_role = Column(String(500), nullable=True)
    what_would_you_most_like_to_improve_right_now = Column(String(500), nullable=True)
    when_are_you_planning_to_upgrade_or_adopt_clinic_software = Column(String(500), nullable=True)
    city = Column(String(100), nullable=True)
    source = Column(String(100), nullable=True)
    row_color = Column(String(32), nullable=True)
    is_unsubscribed = Column(Boolean, default=False, nullable=False)
    unsubscribed_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    campaign = relationship("Campaign", back_populates="campaign_leads")
    assigned_users = relationship("LeadAssignment", back_populates="lead")
    notes = relationship("LeadNote", back_populates="lead")
    tasks = relationship("LeadTask", back_populates="lead")
    calls = relationship("LeadCall", back_populates="lead")
    whatsapp_messages = relationship("LeadWhatsApp", back_populates="lead")
