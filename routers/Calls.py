from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from models.LeadCallModel import LeadCall
from models.LeadsModel import Lead
from models.UsersModel import User
from schemas.CallSchema import CallCreate, CallOut, CallsByLeadIdsRequest
from routers.auth import get_current_user, get_admin_user
from utils.activity import set_activity_description, describe_created, describe_updated, describe_deleted
from typing import List, Dict
from datetime import datetime, date
from utils.datetime_utils import ist_now

router = APIRouter(prefix="/calls", tags=["Calls"])


# Log a call for a lead
@router.post("/create-call", response_model=CallOut)
def log_call(request: Request, data: CallCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Verify lead exists
    lead = db.query(Lead).filter(Lead.id == data.lead_id, Lead.is_deleted == False).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Create call record
    call = LeadCall(
        lead_id=data.lead_id,
        call_status=data.call_status,
        call_duration=data.call_duration,
        note=data.note,
        call_note_date=data.call_note_date,
        created_by=current_user.username
    )
    
    # Increment call count on lead
    lead.call_count += 1
    
    db.add(call)
    db.commit()
    db.refresh(call)
    set_activity_description(request, describe_created("call", f"lead #{data.lead_id}", data.call_status or ""))
    return call


# Get call history for a lead
@router.get("/get-calls-by-lead/{lead_id}", response_model=List[CallOut])
def get_calls_by_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.is_deleted == False).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    calls = db.query(LeadCall).filter(LeadCall.lead_id == lead_id, LeadCall.is_deleted == False).order_by(LeadCall.created_at.desc()).all()
    return calls


# Bulk endpoint to reduce N+1 requests
@router.post("/by-lead-ids", response_model=Dict[str, List[CallOut]])
def get_calls_by_lead_ids(
    data: CallsByLeadIdsRequest,
    db: Session = Depends(get_db),
):
    lead_ids = data.lead_ids or []
    if not lead_ids:
        raise HTTPException(status_code=400, detail="lead_ids is required")

    calls = (
        db.query(LeadCall)
        .filter(LeadCall.lead_id.in_(lead_ids), LeadCall.is_deleted == False)
        .order_by(LeadCall.lead_id.asc(), LeadCall.created_at.desc())
        .all()
    )

    # JSON object keys are always strings
    result: Dict[str, List[CallOut]] = {str(lid): [] for lid in lead_ids}
    for call in calls:
        result[str(call.lead_id)].append(CallOut.model_validate(call))
    return result


# Get a single call by ID
@router.get("/get-call-by-id/{call_id}", response_model=CallOut)
def get_call(call_id: int, db: Session = Depends(get_db)):
    call = db.query(LeadCall).filter(LeadCall.id == call_id, LeadCall.is_deleted == False).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return call


# Update a call record
@router.put("/update-call/{call_id}", response_model=CallOut)
def update_call(
    request: Request,
    call_id: int,
    call_status: str = None,
    call_duration: int = None,
    note: str = None,
    call_note_date: date = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    call = db.query(LeadCall).filter(LeadCall.id == call_id, LeadCall.is_deleted == False).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    
    changes = []
    if call_status is not None:
        call.call_status = call_status
        changes.append("status")
    if call_duration is not None:
        call.call_duration = call_duration
        changes.append("duration")
    if note is not None:
        call.note = note
        changes.append("note")
    if call_note_date is not None:
        call.call_note_date = call_note_date
        changes.append("note_date")
    
    db.commit()
    db.refresh(call)
    set_activity_description(request, describe_updated("call", f"#{call_id}", ", ".join(changes) if changes else "details"))
    return call


# Delete a call record (soft delete)
@router.delete("/delete-call/{call_id}")
def delete_call(request: Request, call_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    call = db.query(LeadCall).filter(LeadCall.id == call_id, LeadCall.is_deleted == False).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    
    lead_id = call.lead_id
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if lead and lead.call_count > 0:
        lead.call_count -= 1
    
    call.is_deleted = True
    call.deleted_at = ist_now()
    db.commit()
    set_activity_description(request, describe_deleted("call", f"#{call_id}", f"lead #{lead_id}"))
    return {"detail": "Call deleted successfully"}


# Hard delete a call (Admin only)
@router.delete("/delete-call/{call_id}/hard-delete")
def hard_delete_call(request: Request, call_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    call = db.query(LeadCall).filter(LeadCall.id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    lead_id = call.lead_id
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if lead and lead.call_count > 0:
        lead.call_count -= 1
    db.delete(call)
    db.commit()
    set_activity_description(request, describe_deleted("call (hard)", f"#{call_id}", f"lead #{lead_id}"))
    return {"detail": "Call permanently deleted"}

