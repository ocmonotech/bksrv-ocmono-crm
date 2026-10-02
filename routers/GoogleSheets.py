from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import SessionLocal, get_db
from models.GoogleSheetConnectionModel import GoogleSheetConnection, GoogleSheetSyncLog
from models.LeadsModel import Lead
from schemas.GoogleSheetSchema import (GoogleSheetConnectionCreate,GoogleSheetConnectionUpdate,GoogleSheetConnectionOut,SyncLogOut,GoogleSheetStats,FieldMapping)
from routers.auth import get_current_user
from typing import List, Optional
from datetime import datetime, timedelta
from utils.datetime_utils import IST, ist_now
import re


def _now_ist():
    """Current time in India (IST), timezone-aware."""
    return ist_now()


def parse_lead_datetime(value):
    """
    Convert incoming date/datetime from sheet to DB-safe naive datetime (IST) for MySQL DATETIME columns.
    Handles None, empty string, datetime, or ISO string (e.g. 2026-03-13T19:48:08-05:00 or with Z).
    """
    if value in (None, "", "null"):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except (ValueError, TypeError):
            # Fallback to date-only parse (returns naive datetime, fine for MySQL)
            return parse_date(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(IST).replace(tzinfo=None)
    return dt


# Lead fields that may come from sheet as datetime strings; normalize before insert
LEAD_DATETIME_FIELDS = ("lead_date",)


import os
from dotenv import load_dotenv

load_dotenv()

# Optional imports for Google Sheets API
try:
    import requests
    import csv
    import io
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("⚠️  requests not installed. Install with: pip install requests")

router = APIRouter(prefix="/google-sheets", tags=["Google Sheets Integration"])


def _is_sheet_connection_active(connection: GoogleSheetConnection) -> bool:
    return (connection.status or "").strip().lower() == "active"


def _as_ist(dt: Optional[datetime]) -> Optional[datetime]:
    """MySQL may return naive datetimes; normalize for comparison with ist_now()."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def _sync_frequency_delta(sync_frequency: Optional[str]) -> timedelta:
    sync_freq_map = {
        "Every 15 minutes": timedelta(minutes=15),
        "Every 30 minutes": timedelta(minutes=30),
        "Hourly": timedelta(hours=1),
        "Daily": timedelta(days=1),
    }
    return sync_freq_map.get((sync_frequency or "").strip(), timedelta(minutes=15))


def _connection_should_sync_now(connection: GoogleSheetConnection, now: datetime) -> bool:
    """
    True if a periodic import should run. Uses both next_sync and (last_sync + frequency)
    so we still sync if next_sync was never updated or is wrong in the DB.
    """
    if not connection.field_mapping or not isinstance(connection.field_mapping, list):
        return False
    if len(connection.field_mapping) == 0:
        return False
    if not _is_sheet_connection_active(connection):
        return False
    ns = _as_ist(connection.next_sync)
    if ns is None or ns <= now:
        return True
    interval = _sync_frequency_delta(connection.sync_frequency)
    ls = _as_ist(connection.last_sync)
    if ls is None:
        return True
    return (now - ls) >= interval


def extract_sheet_id_from_url(url: str) -> Optional[str]:
    """Extract Google Sheet ID from URL"""
    # Pattern: https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else None


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse date string to datetime object"""
    if not date_str:
        return None
    try:
        # Try common date formats
        if isinstance(date_str, str):
            # Try YYYY-MM-DD format
            if len(date_str) == 10 and date_str.count('-') == 2:
                return datetime.strptime(date_str, '%Y-%m-%d')
            # Try MM/DD/YYYY format
            elif len(date_str) == 10 and date_str.count('/') == 2:
                return datetime.strptime(date_str, '%m/%d/%Y')
            # Try DD/MM/YYYY format
            elif len(date_str) == 10 and date_str.count('/') == 2:
                return datetime.strptime(date_str, '%d/%m/%Y')
        return None
    except (ValueError, AttributeError):
        return None


def _get_row_value(row: dict, sheet_column: str, headers: list) -> str:
    """Get value from row by sheet column name or position. Uses case-insensitive and trimmed matching for header names."""
    val = ""
    if sheet_column.startswith("Column "):
        col_letter = sheet_column.replace("Column ", "").strip()
        col_index = ord(col_letter.upper()) - ord("A")
        if col_index < len(headers) and headers[col_index] is not None:
            header_name = headers[col_index]
            val = row.get(header_name, "") or ""
        return (val or "").strip()
    # Direct column name: try exact key first, then case-insensitive + stripped match
    exact = row.get(sheet_column, "")
    if exact != "":
        return str(exact).strip()
    key_lower = sheet_column.strip().lower()
    for key in row:
        if key is not None and key.strip().lower() == key_lower:
            return (row.get(key) or "").strip()
    return ""


def get_sheet_data_from_csv(connection: GoogleSheetConnection):
    """Read Google Sheet data using public CSV export URL"""
    if not REQUESTS_AVAILABLE:
        raise Exception("requests library not installed. Install with: pip install requests")
    
    try:
        # Construct CSV export URL
        # Format: https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}
        csv_url = f"https://docs.google.com/spreadsheets/d/{connection.sheet_id}/gviz/tq?tqx=out:csv&sheet={connection.sheet_name}"
        
        # Fetch CSV data
        response = requests.get(csv_url, timeout=30)
        response.raise_for_status()
        
        # Parse CSV
        csv_content = response.text
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        records = list(csv_reader)
        
        return records, csv_reader.fieldnames or []
    except Exception as e:
        print(f"Error fetching Google Sheet data: {e}")
        raise


def sync_google_sheet(connection_id: int):
    """Background task to sync leads from Google Sheet"""
    db = SessionLocal()
    try:
        connection = db.query(GoogleSheetConnection).filter(GoogleSheetConnection.id == connection_id).first()
        if not connection:
            print(f"Connection {connection_id} not found")
            return
        
        if not _is_sheet_connection_active(connection):
            print(f"Connection {connection_id} is not active")
            return
        
        if not connection.field_mapping:
            raise Exception("Field mapping not configured")
        
        # Get sheet data using CSV export
        records, headers = get_sheet_data_from_csv(connection)
        
        # Create mapping dictionary
        column_mapping = {}
        required_fields = []
        for mapping in connection.field_mapping:
            column_mapping[mapping['lead_field']] = mapping['sheet_column']
            if mapping.get('required'):
                required_fields.append(mapping['lead_field'])
        
        # Import leads
        imported_count = 0
        skipped_empty = 0
        skipped_duplicate = 0
        errors = []
        new_lead_ids: List[int] = []
        
        for row in records:
            try:
                # Map sheet columns to lead fields (case-insensitive header match, trimmed values)
                lead_data = {}
                for lead_field, sheet_column in column_mapping.items():
                    lead_data[lead_field] = _get_row_value(row, sheet_column, headers)
                # Normalize datetime fields to DB-safe naive IST for MySQL
                for field in LEAD_DATETIME_FIELDS:
                    lead_data[field] = parse_lead_datetime(lead_data.get(field))
                
                # Skip completely empty rows (no email and no phone and no name)
                if not (lead_data.get('email') or lead_data.get('phone') or lead_data.get('name')):
                    skipped_empty += 1
                    continue
                
                # Check required fields
                if 'email' in required_fields and not lead_data.get('email'):
                    errors.append(f"Row missing required email field")
                    continue
                
                if 'phone' in required_fields and not lead_data.get('phone'):
                    errors.append(f"Row missing required phone field")
                    continue
                
                # Check if lead already exists (by email)
                if lead_data.get('email'):
                    existing_lead = db.query(Lead).filter(Lead.email == lead_data['email'].strip()).first()
                    if existing_lead:
                        skipped_duplicate += 1
                        continue  # Skip existing leads
                
                # Create lead
                # Use campaign_id from connection settings
                # Source: use mapped value if available, otherwise use connection source
                source_value = lead_data.get('source') or connection.source
                
                lead = Lead(
                    name=lead_data.get('name', ''),
                    email=lead_data.get('email', ''),
                    phone=lead_data.get('phone', ''),
                    status='New',
                    priority=lead_data.get('priority', 'low'),
                    campaign_id=connection.campaign_id,  # Use campaign from connection
                    sheets_lead_id=lead_data.get('sheets_lead_id'),
                    ad_name=lead_data.get('ad_name'),
                    platform=lead_data.get('platform'),
                    what_best_describes_your_role=lead_data.get('what_best_describes_your_role'),
                    what_would_you_most_like_to_improve_right_now=lead_data.get('what_would_you_most_like_to_improve_right_now'),
                    when_are_you_planning_to_upgrade_or_adopt_clinic_software=lead_data.get('when_are_you_planning_to_upgrade_or_adopt_clinic_software'),
                    city=lead_data.get('city'),
                    lead_date=lead_data.get('lead_date'),
                    source=source_value,  # Set source field
                    created_at=ist_now(),
                    date_created=ist_now()
                )
                
                db.add(lead)
                db.flush()
                if (lead.email or "").strip():
                    new_lead_ids.append(lead.id)
                imported_count += 1
                
            except Exception as e:
                errors.append(f"Error importing row: {str(e)}")
        
        db.commit()

        from utils.welcome_email import send_welcome_email_to_lead

        for wid in new_lead_ids:
            try:
                send_welcome_email_to_lead(wid)
            except Exception as wel_exc:
                print(f"[GoogleSheets] welcome email for lead {wid}: {wel_exc}")
        
        # Update connection stats (use India time for last_sync)
        connection.last_sync = _now_ist()
        connection.leads_synced += imported_count
        connection.total_leads = len(records)
        if errors:
            connection.errors += len(errors)
        
        frequency_delta = _sync_frequency_delta(connection.sync_frequency)
        connection.next_sync = ist_now() + frequency_delta
        
        # Build clear message for user (especially when 0 imported)
        if imported_count > 0 and not errors:
            msg = f"Successfully synced {imported_count} new leads."
        elif imported_count > 0 and errors:
            msg = f"Synced {imported_count} leads with {len(errors)} errors."
        elif imported_count == 0:
            parts = [f"Sync completed. 0 new leads imported from {len(records)} row(s)."]
            if skipped_duplicate:
                parts.append(f"{skipped_duplicate} skipped (email already exists).")
            if skipped_empty:
                parts.append(f"{skipped_empty} empty row(s) skipped.")
            if errors:
                parts.append(f"{len(errors)} row(s) missing required fields.")
            parts.append("Check that column mapping matches your sheet headers (e.g. 'Email' vs 'E-mail').")
            msg = " ".join(parts)
        else:
            msg = f"Successfully synced {imported_count} new leads."
        
        # Create sync log (use India time so "today" and list order match user's date)
        sync_log = GoogleSheetSyncLog(
            connection_id=connection.id,
            connection_name=connection.connection_name,
            status="Success" if not errors else "Error",
            leads_imported=imported_count,
            message=msg,
            error_details="; ".join(errors) if errors else None,
            created_at=_now_ist(),
        )
        db.add(sync_log)
        db.commit()
        
        print(f"✓ Synced {imported_count} leads from {connection.connection_name}")
        
    except Exception as e:
        # Log error in a fresh session (use India time so today's errors show)
        db_err = SessionLocal()
        try:
            connection = db_err.query(GoogleSheetConnection).filter(GoogleSheetConnection.id == connection_id).first()
            if connection:
                connection.errors += 1
                connection.last_sync = _now_ist()
                sync_log = GoogleSheetSyncLog(
                    connection_id=connection.id,
                    connection_name=connection.connection_name,
                    status="Error",
                    leads_imported=0,
                    message=f"Sync failed: {str(e)[:500]}",
                    error_details=str(e)[:2000],
                    created_at=_now_ist(),
                )
                db_err.add(sync_log)
                db_err.commit()
        finally:
            db_err.close()
        print(f"✗ Error syncing connection {connection_id}: {e}")
    finally:
        db.close()


def run_due_google_sheet_syncs() -> None:
    """
    APScheduler entrypoint: sync connections that are due by next_sync OR by
    last_sync + sync_frequency (covers stale/wrong next_sync in DB).
    """
    db = SessionLocal()
    try:
        now = ist_now()
        candidates = (
            db.query(GoogleSheetConnection)
            .filter(
                func.lower(func.trim(GoogleSheetConnection.status)) == "active",
                GoogleSheetConnection.field_mapping.isnot(None),
            )
            .all()
        )
        for conn in candidates:
            if not _connection_should_sync_now(conn, now):
                continue
            try:
                sync_google_sheet(conn.id)
            except Exception as exc:
                print(f"Scheduled Google Sheet sync error connection_id={conn.id}: {exc}")
    finally:
        db.close()


# Create a new Google Sheet connection
@router.post("/connect", response_model=GoogleSheetConnectionOut)
def connect_google_sheet(
    data: GoogleSheetConnectionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Create a connection entry. Works with public Google Sheets."""
    # Extract sheet ID from URL
    sheet_id = extract_sheet_id_from_url(data.sheet_url)
    if not sheet_id:
        raise HTTPException(status_code=400, detail="Invalid Google Sheet URL")
    
    # Check if connection name already exists
    existing = db.query(GoogleSheetConnection).filter(
        GoogleSheetConnection.connection_name == data.connection_name
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Connection name already exists")
    
    # Validate campaign_id if provided
    if data.campaign_id:
        from models.CampaignModel import Campaign
        campaign = db.query(Campaign).filter(Campaign.id == data.campaign_id).first()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
    
    # Create connection
    connection = GoogleSheetConnection(
        connection_name=data.connection_name,
        sheet_url=data.sheet_url,
        sheet_id=sheet_id,
        sheet_name=data.sheet_name or "Sheet1",
        sync_frequency=data.sync_frequency or "Every 15 minutes",
        status=data.status or "Active",
        campaign_id=data.campaign_id,
        source=data.source,
        is_public=True
    )
    
    db.add(connection)
    db.commit()
    db.refresh(connection)
    
    return connection


# Get all connections
@router.get("/all-connections", response_model=List[GoogleSheetConnectionOut])
def get_connections(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(GoogleSheetConnection)
    
    if search:
        query = query.filter(GoogleSheetConnection.connection_name.ilike(f"%{search}%"))
    
    if status:
        query = query.filter(GoogleSheetConnection.status == status)
    
    query = query.order_by(GoogleSheetConnection.created_at.desc())
    return query.offset(skip).limit(limit).all()


# Get a single connection
@router.get("/get-connection-by-id/{connection_id}", response_model=GoogleSheetConnectionOut)
def get_connection(connection_id: int, db: Session = Depends(get_db)):
    connection = db.query(GoogleSheetConnection).filter(GoogleSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


# Update connection
@router.put("/update-connection/{connection_id}", response_model=GoogleSheetConnectionOut)
def update_connection(
    connection_id: int,
    data: GoogleSheetConnectionUpdate,
    db: Session = Depends(get_db)
):
    connection = db.query(GoogleSheetConnection).filter(GoogleSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    update_data = data.dict(exclude_unset=True)
    
    # Handle field_mapping conversion
    if 'field_mapping' in update_data and update_data['field_mapping']:
        update_data['field_mapping'] = [mapping.dict() if isinstance(mapping, FieldMapping) else mapping 
                                       for mapping in update_data['field_mapping']]
    
    # Update sheet_id if URL changed
    if 'sheet_url' in update_data:
        sheet_id = extract_sheet_id_from_url(update_data['sheet_url'])
        if sheet_id:
            update_data['sheet_id'] = sheet_id
    
    for key, value in update_data.items():
        setattr(connection, key, value)

    if "field_mapping" in update_data and update_data.get("field_mapping"):
        connection.next_sync = ist_now()

    connection.updated_at = ist_now()
    db.commit()
    db.refresh(connection)
    return connection


# Delete connection
@router.delete("/delete-connection/{connection_id}")
def delete_connection(connection_id: int, db: Session = Depends(get_db)):
    connection = db.query(GoogleSheetConnection).filter(GoogleSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    db.delete(connection)
    db.commit()
    return {"message": "Connection deleted successfully"}


# Update field mapping
@router.post("/update-field-mapping/{connection_id}", response_model=GoogleSheetConnectionOut)
def update_field_mapping(
    connection_id: int,
    field_mapping: List[FieldMapping],
    db: Session = Depends(get_db)
):
    connection = db.query(GoogleSheetConnection).filter(GoogleSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    connection.field_mapping = [mapping.dict() for mapping in field_mapping]
    connection.updated_at = ist_now()
    # Pick up by background scheduler quickly after mapping is saved
    connection.next_sync = ist_now()
    db.commit()
    db.refresh(connection)
    return connection


# Manual sync trigger
@router.post("/manual-sync/{connection_id}", response_model=dict)
def sync_connection(
    connection_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    connection = db.query(GoogleSheetConnection).filter(GoogleSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    background_tasks.add_task(sync_google_sheet, connection_id)
    return {"message": "Sync started", "connection_id": connection_id}


# Sync all active connections
@router.post("/sync-all", response_model=dict)
def sync_all_active(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    connections = (
        db.query(GoogleSheetConnection)
        .filter(func.lower(func.trim(GoogleSheetConnection.status)) == "active")
        .all()
    )
    
    for connection in connections:
        background_tasks.add_task(sync_google_sheet, connection.id)
    
    return {"message": f"Sync started for {len(connections)} active connections", "count": len(connections)}


# Get sync logs (most recent first; created_at stored in India time)
@router.get("/sync-logs", response_model=List[SyncLogOut])
def get_sync_logs(
    connection_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db)
):
    query = db.query(GoogleSheetSyncLog)
    if connection_id:
        query = query.filter(GoogleSheetSyncLog.connection_id == connection_id)
    if status:
        query = query.filter(GoogleSheetSyncLog.status == status)
    query = query.order_by(GoogleSheetSyncLog.created_at.desc())
    return query.offset(skip).limit(limit).all()


# Get available columns from a Google Sheet (for field mapping)
@router.get("/connections/{connection_id}/columns")
def get_sheet_columns(connection_id: int, db: Session = Depends(get_db)):
    """Get available columns from the Google Sheet for field mapping"""
    connection = db.query(GoogleSheetConnection).filter(GoogleSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    try:
        # Get sheet data to extract headers
        records, headers = get_sheet_data_from_csv(connection)
        
        # Format as Column A, Column B, etc.
        columns = []
        for idx, header in enumerate(headers):
            col_letter = chr(ord('A') + idx)
            columns.append({
                "column_letter": f"Column {col_letter}",
                "header_name": header or f"Column {col_letter}",
                "index": idx
            })
        
        return {
            "connection_id": connection_id,
            "sheet_name": connection.sheet_name,
            "columns": columns
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch columns: {str(e)}")


# Get available campaigns for selection
@router.get("/available-campaigns")
def get_available_campaigns(db: Session = Depends(get_db)):
    """Get list of all available campaigns for Google Sheets connection"""
    from models.CampaignModel import Campaign
    campaigns = db.query(Campaign).filter(Campaign.status == "Active").all()
    return [
        {
            "id": campaign.id,
            "name": campaign.name,
            "platform": campaign.platform,
            "ad_name": campaign.ad_name
        }
        for campaign in campaigns
    ]


# Get available lead fields for mapping
@router.get("/available-lead-fields")
def get_available_lead_fields():
    """Get list of all available lead fields that can be mapped from Google Sheets"""
    return {
        "basic_fields": [
            {"field": "name", "description": "Lead name", "required": False},
            {"field": "email", "description": "Lead email", "required": True},
            {"field": "phone", "description": "Lead phone", "required": True},
            {"field": "priority", "description": "Lead priority (Low, Medium, High)", "required": False},
            {"field": "source", "description": "Lead source (if not mapped, will use connection source)", "required": False},
        ],
        "google_sheets_fields": [
            {"field": "sheets_lead_id", "description": "Lead ID from Google Sheets", "required": False},
            {"field": "ad_name", "description": "Ad name", "required": False},
            {"field": "platform", "description": "Platform name (e.g., Google Ads, Facebook Ads)", "required": False},
            {"field": "what_best_describes_your_role", "description": "Role description", "required": False},
            {"field": "what_would_you_most_like_to_improve_right_now", "description": "Improvement preference", "required": False},
            {"field": "when_are_you_planning_to_upgrade_or_adopt_clinic_software", "description": "Upgrade timeline", "required": False},
            {"field": "city", "description": "City name", "required": False},
            {"field": "lead_date", "description": "Lead date (datetime format: YYYY-MM-DD, MM/DD/YYYY, or DD/MM/YYYY)", "required": False},
        ],
        "note": "campaign and status are set automatically from connection settings. If source is not mapped, it will use the connection's source value."
    }


# Preview sheet data with mapped fields (without importing)
@router.get("/preview/{connection_id}")
def preview_sheet_data(
    connection_id: int,
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Preview Google Sheet data with mapped fields without importing"""
    connection = db.query(GoogleSheetConnection).filter(GoogleSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    try:
        # Get sheet data
        records, headers = get_sheet_data_from_csv(connection)
        
        # If field mapping exists, map the fields
        mapped_records = []
        if connection.field_mapping:
            column_mapping = {}
            for mapping in connection.field_mapping:
                column_mapping[mapping['lead_field']] = mapping['sheet_column']
            
            for row in records[:limit]:
                mapped_row = {}
                for lead_field, sheet_column in column_mapping.items():
                    if sheet_column.startswith('Column '):
                        col_letter = sheet_column.replace('Column ', '').strip()
                        col_index = ord(col_letter.upper()) - ord('A')
                        if col_index < len(headers):
                            header_name = headers[col_index]
                            mapped_row[lead_field] = row.get(header_name, '')
                        else:
                            mapped_row[lead_field] = ''
                    else:
                        mapped_row[lead_field] = row.get(sheet_column, '')
                mapped_records.append(mapped_row)
        else:
            # Return raw data if no mapping
            for row in records[:limit]:
                mapped_records.append(dict(row))
        
        return {
            "connection_id": connection_id,
            "connection_name": connection.connection_name,
            "total_rows": len(records),
            "preview_rows": limit,
            "headers": headers,
            "field_mapping": connection.field_mapping,
            "data": mapped_records
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to preview sheet data: {str(e)}")


# Get statistics
@router.get("/stats", response_model=GoogleSheetStats)
def get_stats(db: Session = Depends(get_db)):
    active_connections = db.query(GoogleSheetConnection).filter(GoogleSheetConnection.status == "Active").count()
    
    total_leads_synced = db.query(func.sum(GoogleSheetConnection.leads_synced)).scalar() or 0
    
    # Today's syncs
    today_start = ist_now().replace(hour=0, minute=0, second=0, microsecond=0)
    todays_syncs = db.query(GoogleSheetSyncLog).filter(
        GoogleSheetSyncLog.created_at >= today_start
    ).count()
    
    # Total errors
    total_errors = db.query(func.sum(GoogleSheetConnection.errors)).scalar() or 0
    
    return {
        "active_connections": active_connections,
        "total_leads_synced": int(total_leads_synced),
        "todays_syncs": todays_syncs,
        "errors": int(total_errors)
    }

