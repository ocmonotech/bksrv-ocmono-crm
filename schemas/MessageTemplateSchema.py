from pydantic import BaseModel
from typing import Literal, Optional, List
from datetime import datetime


class MessageTemplateBase(BaseModel):
    template_type: Literal["email", "whatsapp", "sms"]
    name: str
    content: str
    category: Optional[str] = None
    tags: Optional[List[str]] = []
    status: Optional[Literal["Draft", "Active"]] = "Draft"
    subject: Optional[str] = None
    editor_mode: Optional[Literal["Plain Text", "Rich Text"]] = "Plain Text"
    variables: Optional[List[str]] = []


class MessageTemplateCreate(MessageTemplateBase):
    pass


class MessageTemplateUpdate(BaseModel):
    template_type: Optional[Literal["email", "whatsapp", "sms"]] = None
    name: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[Literal["Draft", "Active"]] = None
    subject: Optional[str] = None
    content: Optional[str] = None
    editor_mode: Optional[Literal["Plain Text", "Rich Text"]] = None
    variables: Optional[List[str]] = None
    version: Optional[str] = None


class MessageTemplateOut(MessageTemplateBase):
    id: int
    usage_count: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    version: str = "v1"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TemplateAnalytics(BaseModel):
    total_templates: int
    total_usage: int
    avg_success_rate: float
    active_templates: int


class TemplateUsageStats(BaseModel):
    template_id: int
    template_name: str
    usage: int
    success_rate: float


class UsageByType(BaseModel):
    template_type: str
    total_usage: int
    templates: int
