from pydantic import BaseModel
from typing import Optional, Dict, List, Any
from datetime import datetime


class FieldMappingRequest(BaseModel):
    """Request model for field mapping"""
    file_id: int
    field_mapping: Dict[str, str]  # Maps CSV column names to lead field names
    campaign_id: Optional[int] = None
    source: Optional[str] = None
    status: Optional[str] = "New"
    priority: Optional[str] = "Medium"


class ImportPreviewResponse(BaseModel):
    """Response model for file preview"""
    file_id: int
    filename: str
    file_type: str
    total_rows: int
    sample_data: List[Dict[str, Any]]  # First few rows for preview
    available_columns: List[str]  # Column names from the file
    available_lead_fields: List[str]  # Lead fields that can be mapped


class LeadImportOut(BaseModel):
    """Response model for import history"""
    id: int
    filename: str
    file_type: str
    total_records: int
    imported_records: int
    failed_records: int
    status: str
    imported_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ImportDetailsOut(BaseModel):
    """Detailed import information"""
    id: int
    filename: str
    file_type: str
    total_records: int
    imported_records: int
    failed_records: int
    status: str
    field_mapping: Optional[Dict[str, str]] = None
    error_details: Optional[str] = None
    imported_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ImportStatsResponse(BaseModel):
    """Statistics for imports"""
    total_imports: int
    total_records: int
    failed_records: int
    success_rate: float

