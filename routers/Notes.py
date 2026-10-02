from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from models.LeadNoteModel import LeadNote
from models.UsersModel import User
from schemas.NoteSchema import NoteCreate, NoteOut
from routers.auth import get_current_user
from utils.activity import set_activity_description, describe_created
from typing import List


router = APIRouter(prefix="/notes", tags=["Notes"])

# Create a new note for a lead
@router.post("/create", response_model=NoteOut)
def create_note(request: Request, data: NoteCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    note = LeadNote(**data.dict(), created_by=current_user.username)
    db.add(note)
    db.commit()
    db.refresh(note)
    set_activity_description(request, describe_created("note", f"lead #{data.lead_id}", (data.content or "")[:50]))
    return note

# Get notes by lead ID
@router.get("/by-lead/{lead_id}", response_model=List[NoteOut])
def get_notes_by_lead(lead_id: int, db: Session = Depends(get_db)):
    return db.query(LeadNote).filter(LeadNote.lead_id == lead_id, LeadNote.is_deleted == False).all()