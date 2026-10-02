from sqlalchemy import Column, Date, Float, ForeignKey, Integer, String, Text, DateTime, Boolean
from database import Base
from sqlalchemy.orm import relationship

class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    ad_name = Column(String(200), nullable=True)
    platform = Column(String(100), nullable=True)  # Google, Meta, Other
    status = Column(String(50), nullable=True)  # Active, Paused
    budget = Column(Float, nullable=True)
    spent = Column(Float, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(Date, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    impressions = Column(Integer, default=0, nullable=True)
    clicks = Column(Integer, default=0, nullable=True)
    revenue = Column(Float, default=0, nullable=True)
    roas = Column(Float, default=0, nullable=True)
    leads = Column(Integer, default=0, nullable=True)
    converted = Column(Integer, default=0, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    campaign_leads = relationship("Lead", back_populates="campaign")
    booking_links = relationship("CampaignBookingLink", back_populates="campaign", cascade="all, delete-orphan")
