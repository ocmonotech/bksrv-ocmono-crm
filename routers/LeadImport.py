from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models.LeadImportModel import LeadImport
from models.LeadsModel import Lead, LeadAssignment
from schemas.LeadImportSchema import (FieldMappingRequest,ImportPreviewResponse,LeadImportOut,ImportDetailsOut,ImportStatsResponse)
from routers.auth import get_current_user
from typing import List, Optional, Dict, Any
from datetime import datetime
from utils.datetime_utils import ist_now
import csv
import json
import io
import math
from pathlib import Path
from openpyxl import load_workbook, Workbook

router = APIRouter(prefix="/leads/import", tags=["Lead Import"])

# Maximum file size: 10MB
MAX_FILE_SIZE = 10 * 1024 * 1024


def _is_empty_or_nan(v: Any) -> bool:
    """Return True if value is None, NaN, or empty string."""
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str) and v.strip().lower() in ("", "nan", "none", "null"):
        return True
    return False


def parse_file_content(file_content: bytes, file_type: str) -> List[Dict[str, Any]]:
    """Parse uploaded file content from memory and return list of dictionaries"""
    try:
        if file_type.lower() == "csv":
            data = []
            # Decode bytes to string
            content_str = file_content.decode('utf-8')
            content_io = io.StringIO(content_str)
            
            # Try to detect delimiter
            sample = content_str[:1024]
            sniffer = csv.Sniffer()
            delimiter = sniffer.sniff(sample).delimiter
            
            content_io.seek(0)
            reader = csv.DictReader(content_io, delimiter=delimiter)
            for row in reader:
                # Clean up keys (remove spaces)
                cleaned_row = {k.strip(): v.strip() if isinstance(v, str) else v for k, v in row.items() if k}
                if cleaned_row:  # Only add non-empty rows
                    data.append(cleaned_row)
            return data
        
        elif file_type.lower() in ["excel", "xlsx", "xls"]:
            # Read Excel from bytes using openpyxl (.xlsx only; .xls not supported)
            wb = load_workbook(io.BytesIO(file_content), read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            wb.close()
            if not rows:
                return []
            headers = [str(h).strip() if h is not None and not _is_empty_or_nan(h) else f"Column_{i}" for i, h in enumerate(rows[0])]
            cleaned_data = []
            for row in rows[1:]:
                cleaned_row = {}
                for i, v in enumerate(row):
                    if i < len(headers):
                        key = headers[i]
                        if _is_empty_or_nan(v):
                            val = ""
                        else:
                            val = str(v).strip()
                        cleaned_row[key] = val
                if any(cleaned_row.values()):
                    cleaned_data.append(cleaned_row)
            return cleaned_data
        
        elif file_type.lower() == "json":
            # Parse JSON from bytes
            content_str = file_content.decode('utf-8')
            data = json.loads(content_str)
            # If it's a single object, wrap it in a list
            if isinstance(data, dict):
                data = [data]
            elif isinstance(data, list):
                pass  # Already a list
            else:
                raise ValueError("Invalid JSON format")
            return data
        
        elif file_type.lower() == "tsv":
            data = []
            # Decode bytes to string
            content_str = file_content.decode('utf-8')
            content_io = io.StringIO(content_str)
            
            reader = csv.DictReader(content_io, delimiter='\t')
            for row in reader:
                cleaned_row = {k.strip(): v.strip() if isinstance(v, str) else v for k, v in row.items() if k}
                if cleaned_row:
                    data.append(cleaned_row)
            return data
        
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e)}")


def get_available_lead_fields() -> List[str]:
    """Get list of available lead fields that can be mapped"""
    return [
        "name",
        "email",
        "phone",
        "status",
        "priority",
        "tags",
        "sheets_lead_id",
        "ad_name",
        "platform",
        "what_best_describes_your_role",
        "what_would_you_most_like_to_improve_right_now",
        "when_are_you_planning_to_upgrade_or_adopt_clinic_software",
        "city",
        "lead_date",
        "source"
    ]


def parse_date(date_str: Any) -> Optional[datetime]:
    """Parse date string to datetime object"""
    if not date_str:
        return None
    
    # Handle None / NaN / empty
    if _is_empty_or_nan(date_str):
        return None
    
    date_str = str(date_str).strip()
    if not date_str or date_str.lower() in ['nan', 'none', 'null', '']:
        return None
    
    # Common date formats
    date_formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    ]
    
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None


# Upload file endpoint
@router.post("/upload", response_model=ImportPreviewResponse)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Upload a file (CSV, Excel, JSON, or TSV) and return preview - file is processed in memory, not stored on server"""
    
    # Read file content
    file_content = await file.read()
    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File size exceeds maximum allowed size of 10MB")
    
    # Determine file type
    file_ext = Path(file.filename).suffix.lower()
    file_type_map = {
        ".csv": "CSV",
        ".xlsx": "Excel",
        ".xls": "Excel",
        ".json": "JSON",
        ".tsv": "TSV"
    }
    
    file_type = file_type_map.get(file_ext)
    if not file_type:
        raise HTTPException(status_code=400, detail="Unsupported file type. Supported: CSV, Excel (.xlsx, .xls), JSON, TSV")
    
    # Parse file content in memory
    try:
        data = parse_file_content(file_content, file_type)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e)}")
    
    if not data:
        raise HTTPException(status_code=400, detail="File is empty or contains no valid data")
    
    # Get column names
    available_columns = list(data[0].keys()) if data else []
    
    # Create import record with parsed data stored as JSON
    import_record = LeadImport(
        filename=file.filename,
        file_type=file_type,
        file_data=data,  # Store parsed data as JSON
        total_records=len(data),
        status="Pending",
        imported_by=current_user.username
    )
    db.add(import_record)
    db.commit()
    db.refresh(import_record)
    
    # Return preview (first 5 rows)
    sample_data = data[:5]
    
    return ImportPreviewResponse(
        file_id=import_record.id,
        filename=file.filename,
        file_type=file_type,
        total_rows=len(data),
        sample_data=sample_data,
        available_columns=available_columns,
        available_lead_fields=get_available_lead_fields()
    )


# Get available lead fields for mapping
@router.get("/available-fields")
def get_available_fields():
    """Get list of available lead fields that can be mapped"""
    return {
        "available_lead_fields": get_available_lead_fields(),
        "required_fields": ["name", "email", "phone"],
        "optional_fields": [
            "status", "priority", "tags",
            "sheets_lead_id", "ad_name", "platform",
            "what_best_describes_your_role",
            "what_would_you_most_like_to_improve_right_now",
            "when_are_you_planning_to_upgrade_or_adopt_clinic_software",
            "city", "lead_date", "source"
        ]
    }


# Map fields and import leads
@router.post("/import", response_model=ImportDetailsOut)
def import_leads(
    mapping: FieldMappingRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Map fields and import leads from uploaded file"""
    
    # Get import record
    import_record = db.query(LeadImport).filter(LeadImport.id == mapping.file_id).first()
    if not import_record:
        raise HTTPException(status_code=404, detail="Import record not found")
    
    if import_record.status == "Completed":
        raise HTTPException(status_code=400, detail="This import has already been completed")
    
    # Update status to Processing
    import_record.status = "Processing"
    import_record.field_mapping = mapping.field_mapping
    db.commit()
    
    # Get data from stored file_data (parsed and stored as JSON)
    if not import_record.file_data:
        import_record.status = "Failed"
        import_record.error_details = "File data not found"
        db.commit()
        raise HTTPException(status_code=400, detail="File data not found. Please upload the file again.")
    
    data = import_record.file_data
    
    imported_count = 0
    failed_count = 0
    error_messages = []
    welcome_email_lead_ids: List[int] = []
    
    # Required fields
    required_fields = ["name", "email", "phone"]
    mapped_required = [mapping.field_mapping.get(col) for col in mapping.field_mapping.keys() 
                      if mapping.field_mapping[col] in required_fields]
    
    if not all(field in mapped_required for field in required_fields):
        import_record.status = "Failed"
        import_record.error_details = "Required fields (name, email, phone) must be mapped"
        db.commit()
        raise HTTPException(status_code=400, detail="Required fields (name, email, phone) must be mapped")
    
    # Process each row
    for idx, row in enumerate(data, start=1):
        try:
            # Map fields
            lead_data = {}
            
            # Map each column to lead field
            for csv_col, lead_field in mapping.field_mapping.items():
                if csv_col in row:
                    value = row[csv_col]
                    if value and str(value).strip():
                        lead_data[lead_field] = str(value).strip()
            
            # Validate required fields
            if not lead_data.get("name") or not lead_data.get("email") or not lead_data.get("phone"):
                failed_count += 1
                error_messages.append(f"Row {idx}: Missing required fields (name, email, or phone)")
                continue
            
            # Check if lead with same email already exists
            existing_lead = db.query(Lead).filter(Lead.email == lead_data["email"]).first()
            if existing_lead:
                # Update existing lead instead of creating duplicate
                for key, value in lead_data.items():
                    if key not in ["name", "email", "phone"]:  # Don't update required fields
                        if hasattr(existing_lead, key):
                            if key == "lead_date":
                                setattr(existing_lead, key, parse_date(value))
                            elif key == "tags" and isinstance(value, str):
                                # Parse tags if it's a comma-separated string
                                setattr(existing_lead, key, [tag.strip() for tag in value.split(",") if tag.strip()])
                            else:
                                setattr(existing_lead, key, value)
                
                existing_lead.date_updated = ist_now()
                imported_count += 1
                continue
            
            # Set default values
            lead_data["status"] = lead_data.get("status") or mapping.status or "New"
            lead_data["priority"] = lead_data.get("priority") or mapping.priority or "Medium"
            lead_data["campaign_id"] = mapping.campaign_id
            lead_data["source"] = lead_data.get("source") or mapping.source
            lead_data["created_by"] = current_user.username
            lead_data["created_at"] = ist_now()
            lead_data["date_created"] = ist_now()
            
            # Parse special fields
            if "lead_date" in lead_data:
                lead_data["lead_date"] = parse_date(lead_data["lead_date"])
            
            if "tags" in lead_data and isinstance(lead_data["tags"], str):
                lead_data["tags"] = [tag.strip() for tag in lead_data["tags"].split(",") if tag.strip()]
            
            # Create lead
            new_lead = Lead(**lead_data)
            db.add(new_lead)
            db.flush()  # Get the lead ID
            if (new_lead.email or "").strip():
                welcome_email_lead_ids.append(new_lead.id)

            # Handle assigned_to_id if provided (would need to be in mapping)
            # For now, we'll skip this as it's not in the field mapping
            
            imported_count += 1
        
        except Exception as e:
            failed_count += 1
            error_msg = f"Row {idx}: {str(e)}"
            error_messages.append(error_msg)
            continue
    
    # Update import record
    import_record.imported_records = imported_count
    import_record.failed_records = failed_count
    import_record.status = "Completed"
    if error_messages:
        import_record.error_details = "\n".join(error_messages[:100])  # Limit to first 100 errors
    
    db.commit()
    db.refresh(import_record)

    from utils.welcome_email import send_welcome_email_to_lead

    for wid in welcome_email_lead_ids:
        try:
            send_welcome_email_to_lead(wid)
        except Exception as wel_exc:
            print(f"[LeadImport] welcome email for lead {wid}: {wel_exc}")
    
    return import_record


# Get import history
@router.get("/history", response_model=List[LeadImportOut])
def get_import_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get import history"""
    imports = db.query(LeadImport)\
        .order_by(LeadImport.created_at.desc())\
        .offset(skip)\
        .limit(limit)\
        .all()
    return imports


# Get import details
@router.get("/history/{import_id}", response_model=ImportDetailsOut)
def get_import_details(
    import_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get detailed information about a specific import"""
    import_record = db.query(LeadImport).filter(LeadImport.id == import_id).first()
    if not import_record:
        raise HTTPException(status_code=404, detail="Import record not found")
    return import_record


# Get import statistics
@router.get("/stats", response_model=ImportStatsResponse)
def get_import_stats(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get import statistics"""
    total_imports = db.query(LeadImport).count()
    total_records = db.query(func.sum(LeadImport.total_records)).scalar() or 0
    failed_records = db.query(func.sum(LeadImport.failed_records)).scalar() or 0
    imported_records = db.query(func.sum(LeadImport.imported_records)).scalar() or 0
    
    success_rate = (imported_records / total_records * 100) if total_records > 0 else 0
    
    return ImportStatsResponse(
        total_imports=total_imports,
        total_records=int(total_records),
        failed_records=int(failed_records),
        success_rate=round(success_rate, 2)
    )


# Download CSV template
@router.get("/template/csv")
def download_csv_template():
    """Download CSV template file"""
    # Create sample CSV data
    sample_data = {
        "name": ["John Doe", "Jane Smith"],
        "email": ["john@example.com", "jane@example.com"],
        "phone": ["+1234567890", "+1234567891"],
        "city": ["New York", "Los Angeles"],
        "source": ["Website", "Referral"]
    }
    
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=sample_data.keys())
    writer.writeheader()
    writer.writerows([dict(zip(sample_data.keys(), row)) for row in zip(*sample_data.values())])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=lead_import_template.csv"}
    )


# Download Excel template
@router.get("/template/excel")
def download_excel_template():
    """Download Excel template file"""
    # Create sample data
    sample_data = {
        "name": ["John Doe", "Jane Smith"],
        "email": ["john@example.com", "jane@example.com"],
        "phone": ["+1234567890", "+1234567891"],
        "city": ["New York", "Los Angeles"],
        "source": ["Website", "Referral"]
    }
    headers = list(sample_data.keys())
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append(headers)
    for row in zip(*sample_data.values()):
        ws.append(list(row))
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=lead_import_template.xlsx"}
    )
