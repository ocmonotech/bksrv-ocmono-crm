"""
Meeting room: stores room metadata for video meetings (WebRTC signaling is in-memory).
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now


class MeetingRoom(Base):
    __tablename__ = "meeting_rooms"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(String(64), unique=True, nullable=False, index=True)  # UUID for join link
    title = Column(String(255), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    is_active = Column(Boolean, default=True, nullable=False)

    created_by = relationship("User", foreign_keys=[created_by_id])
