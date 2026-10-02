from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.LeadWhatsAppModel import LeadWhatsApp
from models.LeadsModel import Lead
from models.UsersModel import User
from schemas.WhatsAppSchema import WhatsAppCreate, WhatsAppOut
from routers.auth import get_current_user
from typing import List

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])


# Send/log a WhatsApp message for a lead
@router.post("/send", response_model=WhatsAppOut)
def send_whatsapp_message(data: WhatsAppCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Verify lead exists
    lead = db.query(Lead).filter(Lead.id == data.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Create WhatsApp message record
    whatsapp = LeadWhatsApp(
        lead_id=data.lead_id,
        message_type=data.message_type,
        message_content=data.message_content,
        status=data.status or "sent",
        created_by=current_user.username
    )
    
    # Increment WhatsApp count on lead (only for sent messages)
    if data.message_type == "sent":
        lead.whatsapp_count += 1
    
    db.add(whatsapp)
    db.commit()
    db.refresh(whatsapp)
    
    return whatsapp


# Get WhatsApp message history for a lead
@router.get("/get-whatsapp-by-lead/{lead_id}", response_model=List[WhatsAppOut])
def get_whatsapp_by_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    messages = db.query(LeadWhatsApp).filter(LeadWhatsApp.lead_id == lead_id).order_by(LeadWhatsApp.created_at.desc()).all()
    return messages


# Get a single WhatsApp message by ID
@router.get("/{message_id}", response_model=WhatsAppOut)
def get_whatsapp_message(message_id: int, db: Session = Depends(get_db)):
    message = db.query(LeadWhatsApp).filter(LeadWhatsApp.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


# Update WhatsApp message status
@router.put("/update-whatsapp-status/{message_id}", response_model=WhatsAppOut)
def update_whatsapp_status(
    message_id: int,
    status: str,
    db: Session = Depends(get_db)
):
    message = db.query(LeadWhatsApp).filter(LeadWhatsApp.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    message.status = status
    db.commit()
    db.refresh(message)
    return message


# Delete a WhatsApp message
@router.delete("/delete-whatsapp-message/{message_id}")
def delete_whatsapp_message(message_id: int, db: Session = Depends(get_db)):
    message = db.query(LeadWhatsApp).filter(LeadWhatsApp.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Decrement WhatsApp count on lead (only for sent messages)
    if message.message_type == "sent":
        lead = db.query(Lead).filter(Lead.id == message.lead_id).first()
        if lead and lead.whatsapp_count > 0:
            lead.whatsapp_count -= 1
    
    db.delete(message)
    db.commit()
    return {"detail": "Message deleted successfully"}

