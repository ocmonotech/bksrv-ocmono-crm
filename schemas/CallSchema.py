from pydantic import BaseModel
from datetime import datetime, date
from typing import Optional, List

class CallBase(BaseModel):
    lead_id: int
    call_status: str  # Answered, No Answer, Busy, Voicemail, Failed, etc.
    call_duration: Optional[int] = None  # Duration in seconds
    note: Optional[str] = None
    call_note_date: Optional[date] = None

class CallCreate(CallBase):
    pass

class CallOut(CallBase):
    id: int
    created_by: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class CallsByLeadIdsRequest(BaseModel):
    lead_ids: List[int]

