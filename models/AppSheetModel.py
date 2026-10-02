from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now


class AppSheetConnection(Base):
    __tablename__ = "app_sheet_connections"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    sheet_url = Column(Text, nullable=False)
    sheet_id = Column(String(200), nullable=True)
    sheet_name = Column(String(200), default="Sheet1")
    gid = Column(String(50), nullable=True)
    sync_frequency = Column(String(50), default="Every 15 minutes")
    status = Column(String(50), default="Active")
    headers = Column(JSON, nullable=True)
    row_count = Column(Integer, default=0)
    last_sync = Column(DateTime(timezone=True), nullable=True)
    next_sync = Column(DateTime(timezone=True), nullable=True)
    write_enabled = Column(Boolean, default=True)
    errors = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)

    rows = relationship(
        "AppSheetRow",
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AppSheetRow(Base):
    __tablename__ = "app_sheet_rows"
    __table_args__ = (
        UniqueConstraint("connection_id", "row_number", name="uq_app_sheet_row_number"),
    )

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey("app_sheet_connections.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number = Column(Integer, nullable=False)
    data = Column(JSON, nullable=True)
    checksum = Column(String(64), nullable=True)
    dirty = Column(Boolean, default=False)
    updated_from = Column(String(20), default="google")
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)

    connection = relationship("AppSheetConnection", back_populates="rows")


class AppSheetSyncLog(Base):
    __tablename__ = "app_sheet_sync_logs"

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, nullable=False, index=True)
    connection_name = Column(String(200), nullable=False)
    status = Column(String(50), nullable=False)
    rows_synced = Column(Integer, default=0)
    message = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=ist_now)
