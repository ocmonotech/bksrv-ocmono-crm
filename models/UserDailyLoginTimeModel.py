from sqlalchemy import Column, Integer, Date, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class UserDailyLoginTime(Base):
    """Tracks total time (seconds) each user was logged in per calendar day."""
    __tablename__ = "user_daily_login_time"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    total_seconds_logged_in = Column(Integer, default=0, nullable=False)

    user = relationship("User", foreign_keys=[user_id])
