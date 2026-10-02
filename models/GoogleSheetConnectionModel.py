from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON, ForeignKey
from database import Base
from utils.datetime_utils import ist_now

class GoogleSheetConnection(Base):
    __tablename__ = "google_sheet_connections"

    id = Column(Integer, primary_key=True)
    connection_name = Column(String(200), nullable=False)
    sheet_url = Column(Text, nullable=False)
    sheet_id = Column(String(200), nullable=True)
    sheet_name = Column(String(200), default="Sheet1")
    sync_frequency = Column(String(50), default="Every 15 minutes")  # Every 15 minutes, Every 30 minutes, Hourly, Daily
    status = Column(String(50), default="Active")  # Active, Paused, Inactive
    field_mapping = Column(JSON, nullable=True)  # Store field mappings as JSON
    is_public = Column(Boolean, default=True)  # Whether sheet is publicly accessible
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)  # Default campaign for imported leads
    source = Column(String(200), nullable=True)  # Source name for imported leads
    last_sync = Column(DateTime(timezone=True), default=ist_now, nullable=True)
    next_sync = Column(DateTime(timezone=True), default=ist_now, nullable=True)
    leads_synced = Column(Integer, default=0)
    total_leads = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)


class GoogleSheetSyncLog(Base):
    __tablename__ = "google_sheet_sync_logs"

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, nullable=False)
    connection_name = Column(String(200), nullable=False)
    status = Column(String(50), nullable=False)  # Success, Error
    leads_imported = Column(Integer, default=0)
    message = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=ist_now)

