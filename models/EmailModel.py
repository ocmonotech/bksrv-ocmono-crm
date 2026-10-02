from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from database import Base
from utils.datetime_utils import ist_now

class Email(Base):
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, index=True)
    sender_name = Column(String(255))
    sender_email = Column(String(255))
    receiver_name = Column(String(255))
    receiver_email = Column(String(255))
    subject = Column(String(255))
    message = Column(Text)
    category = Column(String(50))  # Primary, Social, Promotions, etc.
    is_starred = Column(Boolean, default=False)
    is_important = Column(Boolean, default=False)
    is_read = Column(Boolean, default=False)
    is_trashed = Column(Boolean, default=False)
    attachment_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ist_now)
