from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ActivityLogOut(BaseModel):
    id: int
    user_id: int
    username: str
    activity_type: str
    description: Optional[str] = None
    path: Optional[str] = None
    method: Optional[str] = None
    ip_address: Optional[str] = None
    location: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
