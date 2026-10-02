from sqlalchemy import Column, Integer, String, Text, DateTime, Float, JSON, Boolean
from database import Base
from utils.datetime_utils import ist_now

class MessageTemplate(Base):
    __tablename__ = "message_templates"

    id = Column(Integer, primary_key=True)
    template_type = Column(String(50), nullable=False)  # email, whatsapp, sms
    name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=True)
    tags = Column(JSON, nullable=True)  # Array of tags
    status = Column(String(50), default="Draft")  # Draft, Active
    subject = Column(String(500), nullable=True)  # For email templates
    content = Column(Text, nullable=False)
    editor_mode = Column(String(50), default="Plain Text")  # Plain Text, Rich Text
    variables = Column(JSON, nullable=True)  # Array of variable names
    usage_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    success_rate = Column(Float, default=0.0)
    version = Column(String(20), default="v1")
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)