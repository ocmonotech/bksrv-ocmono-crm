"""Models for tracking user PC usage: screen time, bandwidth, running apps, application usage."""
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now


class UserUsageSnapshot(Base):
    """Periodic snapshot from user's PC: screen active time, bandwidth, number of running apps."""
    __tablename__ = "user_usage_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    reported_at = Column(DateTime(timezone=True), nullable=False, index=True)  # When this snapshot was taken
    screen_active_seconds = Column(Integer, default=0, nullable=False)  # Total screen visible/on time (overall)
    mouse_active_seconds = Column(Integer, default=0, nullable=False)  # Mouse/keyboard active = "worked on PC" time
    bandwidth_received_bytes = Column(BigInteger, default=0, nullable=False)
    bandwidth_sent_bytes = Column(BigInteger, default=0, nullable=False)
    applications_running_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=ist_now)

    user = relationship("User", foreign_keys=[user_id])


class UserApplicationUsage(Base):
    """Per-application usage: app name and time used (e.g. in a reporting period)."""
    __tablename__ = "user_application_usage"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    reported_at = Column(DateTime(timezone=True), nullable=False, index=True)  # Period end / report time
    application_name = Column(String(255), nullable=False, index=True)  # e.g. chrome.exe, Code.exe
    usage_seconds = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=ist_now)

    user = relationship("User", foreign_keys=[user_id])


class UserUsageScreenshot(Base):
    """Automatic random screenshots per user (e.g. 5 per day). Stored on disk; this row stores path."""
    __tablename__ = "user_usage_screenshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    captured_at = Column(DateTime(timezone=True), nullable=False, index=True)  # When the screenshot was taken
    file_path = Column(String(512), nullable=False)  # Relative path under SCREENSHOTS_BASE_DIR
    created_at = Column(DateTime(timezone=True), default=ist_now)

    user = relationship("User", foreign_keys=[user_id])
