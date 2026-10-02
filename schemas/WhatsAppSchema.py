from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class WhatsAppBase(BaseModel):
    lead_id: int
    message_type: str  # sent, received
    message_content: str
    status: Optional[str] = None  # sent, delivered, read, failed

class WhatsAppCreate(WhatsAppBase):
    pass

class WhatsAppOut(WhatsAppBase):
    id: int
    created_by: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

