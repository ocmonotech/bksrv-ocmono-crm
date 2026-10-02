from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime


class CampaignBase(BaseModel):
    name: Optional[str] = None
    ad_name: Optional[str] = None
    platform: Optional[str] = None
    status: str
    budget: Optional[float] = None
    manager_id: Optional[int] = None
    start_date: date
    end_date: Optional[date] = None
    description: Optional[str]


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: Optional[str]
    ad_name: Optional[str]
    platform: Optional[str]
    status: Optional[str]
    budget: Optional[float]
    manager_id: Optional[int]
    start_date: Optional[date]
    end_date: Optional[date]
    description: Optional[str]


class CampaignOut(CampaignBase):
    id: int
    spent: Optional[float] = 0
    leads: Optional[int] = 0
    converted: Optional[int] = 0
    revenue: Optional[float] = 0
    roas: Optional[float] = 0
    impressions: Optional[int] = 0
    clicks: Optional[int] = 0
    created_at: Optional[date] = None
    updated_at: Optional[datetime] = None
    class Config:
        from_attributes = True
