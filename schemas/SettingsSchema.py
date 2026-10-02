from pydantic import BaseModel
from typing import Optional

class SettingsBase(BaseModel):
    key: str
    value: Optional[str] = None
    description: Optional[str] = None

class SettingsCreate(SettingsBase):
    pass

class SettingsUpdate(BaseModel):
    value: Optional[str] = None
    description: Optional[str] = None

class SettingsOut(SettingsBase):
    id: int
    
    class Config:
        from_attributes = True

