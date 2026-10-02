"""File Manager model for per-user stored files and metadata."""
from sqlalchemy import Column, Integer, String, BigInteger, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now


class FileRecord(Base):
    __tablename__ = "file_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    extension = Column(String(50), nullable=True)
    mime_type = Column(String(255), nullable=True)
    size_bytes = Column(BigInteger, nullable=False, default=0)

    # Optional derived/metadata fields
    category = Column(String(100), nullable=True)
    tags = Column(Text, nullable=True)  # JSON-encoded array of strings
    notes = Column(Text, nullable=True)

    last_modified_at = Column(DateTime(timezone=True), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=ist_now)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=ist_now)

    user = relationship("User", foreign_keys=[user_id])

