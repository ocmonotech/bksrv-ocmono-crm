from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    username = Column(String(50), nullable=False)
    activity_type = Column(String(50), nullable=False)  # login, logout, create, update, delete, etc.
    description = Column(String(255), nullable=True)  # Human-readable e.g. "Created lead", "Updated campaign"
    path = Column(String(500), nullable=True)  # Request path e.g. /leads
    method = Column(String(10), nullable=True)  # GET, POST, etc.
    ip_address = Column(String(45), nullable=True)  # IPv6 can be up to 45 chars
    location = Column(String(255), nullable=True)  # City, Country (from IP)
    user_agent = Column(String(500), nullable=True)  # Browser/client info
    created_at = Column(DateTime(timezone=True), default=ist_now, index=True)
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id])
