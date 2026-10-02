from sqlalchemy import Column, Integer, ForeignKey, Date, Time, Float, Boolean,String,DateTime
from database import Base
from sqlalchemy.orm import relationship
from utils.datetime_utils import ist_today


class Attendance(Base):
    __tablename__ = "attendances"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), ForeignKey("users.username"))  
    login_time = Column(DateTime, nullable=True)
    logout_time = Column(DateTime, nullable=True)
    date = Column(Date, default=ist_today)

    user = relationship("User", back_populates="attendances")




# class Attendance(Base):
#     __tablename__ = "attendance"

#     id = Column(Integer, primary_key=True, index=True)
#     user_id = Column(Integer, ForeignKey("users.id"))
#     date = Column(Date, default=date.today)
#     clock_in = Column(Time)
#     clock_out = Column(Time, nullable=True)
#     total_hours = Column(Float, nullable=True)
#     is_manual = Column(Boolean, default=False)
#     late = Column(Boolean, default=False)
#     early_leave = Column(Boolean, default=False)

#     user = relationship("User", back_populates="attendances")