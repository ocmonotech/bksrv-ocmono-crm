from typing import List, Optional, Union
from pydantic import BaseModel, field_validator
from datetime import datetime


class FileRecordBase(BaseModel):
    name: str
    extension: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: int
    category: Optional[str] = None
    tags: List[str] = []
    notes: Optional[str] = None
    last_modified_at: Optional[datetime] = None

    @field_validator("tags", mode="before")
    @classmethod
    def ensure_tags_list(cls, v: Union[str, List[str], None]):
        if v is None:
            return []
        if isinstance(v, list):
            return v
        # Comma-separated string -> list
        return [t.strip() for t in str(v).split(",") if t.strip()]


class FileRecordCreate(FileRecordBase):
    pass


class FileRecordUpdate(BaseModel):
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None

    @field_validator("tags", mode="before")
    @classmethod
    def ensure_tags_list(cls, v: Union[str, List[str], None]):
        if v is None:
            return None
        if isinstance(v, list):
            return v
        return [t.strip() for t in str(v).split(",") if t.strip()]


class FileRecordOut(BaseModel):
    id: int
    name: str
    extension: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: int
    last_modified_at: Optional[datetime] = None
    category: Optional[str] = None
    tags: List[str] = []
    notes: Optional[str] = None
    uploaded_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FileManagerStats(BaseModel):
    used_bytes: int
    quota_bytes: int
    remaining_bytes: int
    total_files: int

