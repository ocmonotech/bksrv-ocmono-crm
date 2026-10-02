from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, List
from datetime import datetime

class FieldMapping(BaseModel):
    lead_field: str
    sheet_column: str
    required: bool = False

class GoogleSheetConnectionBase(BaseModel):
    connection_name: str
    sheet_url: str
    sheet_name: Optional[str] = "Sheet1"
    sync_frequency: Optional[str] = "Every 15 minutes"  # Every 15 minutes, Every 30 minutes, Hourly, Daily
    status: Optional[str] = "Active"
    campaign_id: Optional[int] = None  # Default campaign for imported leads
    source: Optional[str] = None  # Source name for imported leads

class GoogleSheetConnectionCreate(GoogleSheetConnectionBase):
    pass

class GoogleSheetConnectionUpdate(BaseModel):
    connection_name: Optional[str] = None
    sheet_url: Optional[str] = None
    sheet_name: Optional[str] = None
    sync_frequency: Optional[str] = None
    status: Optional[str] = None
    campaign_id: Optional[int] = None
    source: Optional[str] = None
    field_mapping: Optional[List[FieldMapping]] = None

class GoogleSheetConnectionOut(GoogleSheetConnectionBase):
    id: int
    sheet_id: Optional[str] = None
    field_mapping: Optional[List[FieldMapping]] = None
    campaign_id: Optional[int] = None
    source: Optional[str] = None
    last_sync: Optional[datetime] = None
    next_sync: Optional[datetime] = None
    leads_synced: int = 0
    total_leads: int = 0
    errors: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class SyncLogOut(BaseModel):
    id: int
    connection_id: int
    connection_name: str
    status: str
    leads_imported: int = 0
    message: Optional[str] = None
    error_details: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

class GoogleSheetStats(BaseModel):
    active_connections: int
    total_leads_synced: int
    todays_syncs: int
    errors: int

class OAuthCallback(BaseModel):
    code: str
    connection_id: Optional[int] = None

