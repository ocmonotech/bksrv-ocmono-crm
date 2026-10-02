from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    message = Column(String(500), nullable=False)
    type = Column(String(50), nullable=False, default="general")
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    target_url = Column(String(500), nullable=True)
    entity_id = Column(Integer, nullable=True)

    user = relationship("User")
