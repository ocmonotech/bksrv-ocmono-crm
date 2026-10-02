from sqlalchemy import Column, Integer, String, Text, DateTime
from database import Base
from utils.datetime_utils import ist_now


class BusinessProfile(Base):
    __tablename__ = "business_profiles"

    id = Column(Integer, primary_key=True, index=True)
    business_name = Column(String(255), nullable=False)
    trading_name = Column(String(255), nullable=True)
    industry_sector = Column(String(150), nullable=True)
    tax_company_registration_id = Column(String(150), nullable=True)

    public_business_email = Column(String(255), nullable=True)
    main_phone = Column(String(50), nullable=True)
    website = Column(String(255), nullable=True)

    address_line_1 = Column(String(255), nullable=True)
    address_line_2 = Column(String(255), nullable=True)
    city = Column(String(120), nullable=True)
    state_region = Column(String(120), nullable=True)
    postal_zip_code = Column(String(50), nullable=True)
    country = Column(String(120), nullable=True)

    short_description = Column(Text, nullable=True)
    logo_url = Column(String(512), nullable=True)

    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)
