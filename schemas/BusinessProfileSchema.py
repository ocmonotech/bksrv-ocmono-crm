from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class BusinessProfileUpsert(BaseModel):
    business_name: str
    trading_name: Optional[str] = None
    industry_sector: Optional[str] = None
    tax_company_registration_id: Optional[str] = None

    public_business_email: Optional[str] = None
    main_phone: Optional[str] = None
    website: Optional[str] = None

    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    state_region: Optional[str] = None
    postal_zip_code: Optional[str] = None
    country: Optional[str] = None

    short_description: Optional[str] = None
    logo_url: Optional[str] = None


class BusinessProfileOut(BaseModel):
    id: int
    business_name: str
    trading_name: Optional[str] = None
    industry_sector: Optional[str] = None
    tax_company_registration_id: Optional[str] = None

    public_business_email: Optional[str] = None
    main_phone: Optional[str] = None
    website: Optional[str] = None

    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    state_region: Optional[str] = None
    postal_zip_code: Optional[str] = None
    country: Optional[str] = None

    short_description: Optional[str] = None
    logo_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
