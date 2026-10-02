from sqlalchemy import Column, Integer, String, DateTime, JSON, Text
from database import Base
from utils.datetime_utils import ist_now


class LeadImport(Base):
    __tablename__ = "lead_imports"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # CSV, Excel, JSON, TSV
    file_data = Column(JSON, nullable=True)  # Store parsed file data as JSON (file not stored on server)
    total_records = Column(Integer, default=0)
    imported_records = Column(Integer, default=0)
    failed_records = Column(Integer, default=0)
    status = Column(String(50), default="Pending")  # Pending, Processing, Completed, Failed
    field_mapping = Column(JSON, nullable=True)  # Store the field mapping used
    error_details = Column(Text, nullable=True)  # Store error details for failed records
    imported_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)

