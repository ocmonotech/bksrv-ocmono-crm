from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.BusinessProfileModel import BusinessProfile
from models.UsersModel import User
from routers.auth import get_current_user
from schemas.BusinessProfileSchema import BusinessProfileUpsert, BusinessProfileOut
from typing import Optional
import os
import uuid

router = APIRouter(prefix="/business-profile", tags=["Business Profile"])

BUSINESS_LOGO_FS_DIR = os.path.join("assets", "uploads", "businessprofiles")
BUSINESS_LOGO_URL_PREFIX = "/static/uploads/businessprofiles"
BUSINESS_LOGO_MAX_BYTES = 5 * 1024 * 1024
BUSINESS_LOGO_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def _clean_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    out = value.strip()
    return out if out else None


def _get_single_profile(db: Session) -> Optional[BusinessProfile]:
    return db.query(BusinessProfile).order_by(BusinessProfile.id.asc()).first()


def _remove_logo_file_if_ours(stored_url: Optional[str]) -> None:
    if not stored_url:
        return
    if not stored_url.startswith(BUSINESS_LOGO_URL_PREFIX + "/"):
        return
    rel = stored_url[len("/static/") :] if stored_url.startswith("/static/") else ""
    if not rel:
        return
    file_path = os.path.join("assets", rel)
    if os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass


@router.get("/get-business-profile", response_model=Optional[BusinessProfileOut])
def get_business_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_single_profile(db)


@router.post("/create-or-update", response_model=BusinessProfileOut)
def create_or_update_business_profile(
    data: BusinessProfileUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = _get_single_profile(db)
    payload = {
        "business_name": data.business_name.strip(),
        "trading_name": _clean_optional(data.trading_name),
        "industry_sector": _clean_optional(data.industry_sector),
        "tax_company_registration_id": _clean_optional(data.tax_company_registration_id),
        "public_business_email": _clean_optional(data.public_business_email),
        "main_phone": _clean_optional(data.main_phone),
        "website": _clean_optional(data.website),
        "address_line_1": _clean_optional(data.address_line_1),
        "address_line_2": _clean_optional(data.address_line_2),
        "city": _clean_optional(data.city),
        "state_region": _clean_optional(data.state_region),
        "postal_zip_code": _clean_optional(data.postal_zip_code),
        "country": _clean_optional(data.country),
        "short_description": _clean_optional(data.short_description),
        "logo_url": _clean_optional(data.logo_url),
    }

    if not payload["business_name"]:
        raise HTTPException(status_code=400, detail="business_name is required")

    if profile:
        for key, val in payload.items():
            setattr(profile, key, val)
    else:
        profile = BusinessProfile(**payload)
        db.add(profile)

    db.commit()
    db.refresh(profile)
    return profile


@router.post("/upload-logo", response_model=BusinessProfileOut)
async def upload_business_profile_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = _get_single_profile(db)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Create business profile first before uploading logo",
        )

    ext = os.path.splitext((file.filename or "").lower())[1]
    if ext not in BUSINESS_LOGO_ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="Unsupported logo file type")

    content = await file.read()
    if len(content) > BUSINESS_LOGO_MAX_BYTES:
        raise HTTPException(status_code=400, detail="File too large. Max size is 5MB")

    os.makedirs(BUSINESS_LOGO_FS_DIR, exist_ok=True)
    fname = f"business_profile_{uuid.uuid4().hex}{ext}"
    fpath = os.path.join(BUSINESS_LOGO_FS_DIR, fname)
    with open(fpath, "wb") as out:
        out.write(content)

    _remove_logo_file_if_ours(profile.logo_url)
    profile.logo_url = f"{BUSINESS_LOGO_URL_PREFIX}/{fname}"
    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/delete-logo", response_model=BusinessProfileOut)
def remove_business_profile_logo(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = _get_single_profile(db)
    if not profile:
        raise HTTPException(status_code=404, detail="Business profile not found")
    _remove_logo_file_if_ours(profile.logo_url)
    profile.logo_url = None
    db.commit()
    db.refresh(profile)
    return profile
