from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class NoteBase(BaseModel):
    lead_id: int
    content: str


class NoteCreate(NoteBase):
    pass


class NoteOut(NoteBase):
    id: int
    created_by: Optional[str] = None
    created_at: datetime
    class Config:
        from_attributes = True
