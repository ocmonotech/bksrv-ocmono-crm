from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Date
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now


class PunchMachineImport(Base):
    """One row per uploaded biometric / punch export file."""

    __tablename__ = "punch_machine_imports"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    imported_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    imported_by_username = Column(String(50), nullable=True)
    imported_at = Column(DateTime(timezone=True), default=ist_now)
    rows_imported = Column(Integer, default=0)
    rows_skipped = Column(Integer, default=0)
    skip_reasons_sample = Column(Text, nullable=True)  # JSON array string of first few error messages
    detected_format = Column(String(80), nullable=True)
    report_year = Column(Integer, nullable=True)
    report_month = Column(Integer, nullable=True)
    statistics_json = Column(Text, nullable=True)  # Statistical Report of Attendance rows (JSON array)

    punches = relationship("PunchMachinePunch", back_populates="import_batch", cascade="all, delete-orphan")
    schedule_days = relationship(
        "PunchMachineScheduleDay", back_populates="import_batch", cascade="all, delete-orphan"
    )
    exception_days = relationship(
        "PunchMachineExceptionDay", back_populates="import_batch", cascade="all, delete-orphan"
    )


class PunchMachinePunch(Base):
    """Single punch timestamp from machine export (first/last of day derived in reports)."""

    __tablename__ = "punch_machine_punches"

    id = Column(Integer, primary_key=True, index=True)
    import_id = Column(Integer, ForeignKey("punch_machine_imports.id"), nullable=False, index=True)
    username = Column(String(50), nullable=False, index=True)
    punch_at = Column(DateTime, nullable=False, index=True)
    raw_row = Column(Text, nullable=True)

    import_batch = relationship("PunchMachineImport", back_populates="punches")


class PunchMachineScheduleDay(Base):
    """Schedule Information Report: per employee per calendar day code (1=present, 25=leave, 26=out, empty=off)."""

    __tablename__ = "punch_machine_schedule_days"

    id = Column(Integer, primary_key=True, index=True)
    import_id = Column(Integer, ForeignKey("punch_machine_imports.id"), nullable=False, index=True)
    machine_user_key = Column(String(80), nullable=False, index=True)
    username = Column(String(50), nullable=True, index=True)
    work_date = Column(Date, nullable=False, index=True)
    code = Column(String(20), nullable=True)

    import_batch = relationship("PunchMachineImport", back_populates="schedule_days")


class PunchMachineExceptionDay(Base):
    """Exception Statistic Report: machine-reported minutes per day (may have no punch rows)."""

    __tablename__ = "punch_machine_exception_days"

    id = Column(Integer, primary_key=True, index=True)
    import_id = Column(Integer, ForeignKey("punch_machine_imports.id"), nullable=False, index=True)
    machine_user_key = Column(String(80), nullable=False, index=True)
    username = Column(String(50), nullable=True, index=True)
    work_date = Column(Date, nullable=False, index=True)
    late_min = Column(Integer, nullable=True)
    early_min = Column(Integer, nullable=True)
    absence_min = Column(Integer, nullable=True)
    total_min = Column(Integer, nullable=True)
    raw_json = Column(Text, nullable=True)

    import_batch = relationship("PunchMachineImport", back_populates="exception_days")
