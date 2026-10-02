from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now

class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    leave_type = Column(String(100))  # e.g. Sick, Casual
    start_date = Column(Date)
    end_date = Column(Date)
    reason = Column(Text)
    status = Column(String(100), default="Pending")  # Pending / Approved / Rejected
    applied_on = Column(DateTime(timezone=True), default=ist_now)

    user = relationship("User")


class LeaveBalance(Base):
    __tablename__ = "leave_balances"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    leave_type = Column(String(100))  # Casual, Sick, etc.
    total = Column(Integer, default=0)
    used = Column(Integer, default=0)

    user = relationship("User")


class Holiday(Base):
    __tablename__ = "holidays"

    id = Column(Integer, primary_key=True, index=True)
    holiday_date = Column(Date, unique=True, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    created_by_username = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ist_now)
