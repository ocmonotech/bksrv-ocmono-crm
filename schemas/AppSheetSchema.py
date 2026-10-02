from pydantic import BaseModel
from typing import Optional, Dict, List, Any
from datetime import datetime


class AppSheetConnectionCreate(BaseModel):
    name: str
    sheet_url: str
    sheet_name: Optional[str] = "Sheet1"
    sync_frequency: Optional[str] = "Every 15 minutes"
    status: Optional[str] = "Active"


class AppSheetConnectionUpdate(BaseModel):
    name: Optional[str] = None
    sheet_url: Optional[str] = None
    sheet_name: Optional[str] = None
    sync_frequency: Optional[str] = None
    status: Optional[str] = None
    write_enabled: Optional[bool] = None


class AppSheetConnectionOut(BaseModel):
    id: int
    name: str
    sheet_url: str
    sheet_id: Optional[str] = None
    sheet_name: Optional[str] = "Sheet1"
    gid: Optional[str] = None
    sync_frequency: Optional[str] = None
    status: Optional[str] = "Active"
    headers: Optional[List[str]] = None
    row_count: int = 0
    last_sync: Optional[datetime] = None
    next_sync: Optional[datetime] = None
    write_enabled: bool = True
    errors: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AppSheetRowOut(BaseModel):
    id: int
    connection_id: int
    row_number: int
    data: Dict[str, Any] = {}
    dirty: bool = False
    updated_from: Optional[str] = None
    updated_at: Optional[datetime] = None
    write_error: Optional[str] = None

    class Config:
        from_attributes = True


class AppSheetRowsPage(BaseModel):
    connection: AppSheetConnectionOut
    headers: List[str] = []
    total: int = 0
    skip: int = 0
    limit: int = 100
    rows: List[AppSheetRowOut] = []
    write_ready: bool = False


class AppSheetRowUpdate(BaseModel):
    values: Dict[str, Any]


class AppSheetRowCreate(BaseModel):
    values: Dict[str, Any] = {}


class AppSheetSyncLogOut(BaseModel):
    id: int
    connection_id: int
    connection_name: str
    status: str
    rows_synced: int = 0
    message: Optional[str] = None
    error_details: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AppSheetStats(BaseModel):
    active_connections: int
    total_rows: int
    todays_syncs: int
    errors: int
    write_ready: bool = False
    service_account_email: Optional[str] = None


class AppSheetCredentialsIn(BaseModel):
    service_account_json: str


class AppSheetCredentialsOut(BaseModel):
    configured: bool
    write_ready: bool
    client_email: Optional[str] = None
    message: Optional[str] = None
