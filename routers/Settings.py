from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from database import get_db
from models.SettingsModel import Settings
from schemas.SettingsSchema import SettingsCreate, SettingsUpdate, SettingsOut
from typing import List, Optional
from pydantic import BaseModel

router = APIRouter(prefix="/settings", tags=["Settings"])


# Get all settings
@router.get("/get-all-settings", response_model=List[SettingsOut])
def get_all_settings(db: Session = Depends(get_db)):
    return db.query(Settings).all()


# Get a setting by key
@router.get("/get-setting-by-key/{key}", response_model=SettingsOut)
def get_setting(key: str, db: Session = Depends(get_db)):
    setting = db.query(Settings).filter(Settings.key == key).first()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")
    return setting


# Create or update a setting
@router.post("/create-or-update-setting/{key}", response_model=SettingsOut)
def set_setting(key: str, value: str, description: Optional[str] = None, db: Session = Depends(get_db)):
    setting = db.query(Settings).filter(Settings.key == key).first()
    
    if setting:
        setting.value = value
        if description:
            setting.description = description
    else:
        setting = Settings(key=key, value=value, description=description)
        db.add(setting)
    
    db.commit()
    db.refresh(setting)
    return setting


# Update a setting
@router.put("/update-setting/{key}", response_model=SettingsOut)
def update_setting(key: str, data: SettingsUpdate, db: Session = Depends(get_db)):
    setting = db.query(Settings).filter(Settings.key == key).first()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")
    
    if data.value is not None:
        setting.value = data.value
    if data.description is not None:
        setting.description = data.description
    
    db.commit()
    db.refresh(setting)
    return setting


# Get default welcome email template ID
@router.get("/get-welcome-email-template/id", response_model=dict)
def get_welcome_email_template_id(db: Session = Depends(get_db)):
    setting = db.query(Settings).filter(Settings.key == "welcome_email_template_id").first()
    if not setting or not setting.value:
        return {"template_id": None, "message": "No default template set"}
    return {"template_id": int(setting.value)}


# Set default welcome email template ID
@router.post("/set-welcome-email-template/{template_id}")
def set_welcome_email_template(template_id: int, db: Session = Depends(get_db)):
    setting = db.query(Settings).filter(Settings.key == "welcome_email_template_id").first()
    
    if setting:
        setting.value = str(template_id)
    else:
        setting = Settings(
            key="welcome_email_template_id",
            value=str(template_id),
            description="Default email template ID for sending welcome emails to new leads"
        )
        db.add(setting)
    
    db.commit()
    return {"message": "Welcome email template set successfully", "template_id": template_id}


# Enable/Disable automatic welcome emails
@router.post("/auto-welcome-email/{enabled}")
def set_auto_welcome_email(enabled: bool, db: Session = Depends(get_db)):
    setting = db.query(Settings).filter(Settings.key == "auto_welcome_email_enabled").first()
    
    if setting:
        setting.value = str(enabled).lower()
    else:
        setting = Settings(
            key="auto_welcome_email_enabled",
            value=str(enabled).lower(),
            description="Enable or disable automatic welcome emails when leads are created"
        )
        db.add(setting)
    
    db.commit()
    return {
        "message": f"Automatic welcome emails {'enabled' if enabled else 'disabled'}",
        "enabled": enabled
    }


# Get automatic welcome email status
@router.get("/auto-welcome-email/status", response_model=dict)
def get_auto_welcome_email_status(db: Session = Depends(get_db)):
    setting = db.query(Settings).filter(Settings.key == "auto_welcome_email_enabled").first()
    if not setting or not setting.value:
        # Default to enabled if not set
        return {"enabled": True, "message": "Automatic welcome emails are enabled (default)"}
    enabled = setting.value.lower() == "true"
    return {"enabled": enabled, "message": f"Automatic welcome emails are {'enabled' if enabled else 'disabled'}"}


# --- Screenshot (user usage) settings ---
# retention_days: 0 = keep forever; >0 = delete screenshots older than N days
# visible_to: "user_and_admin" | "user_only" | "admin_only"
SCREENSHOT_VISIBLE_VALUES = ("user_and_admin", "user_only", "admin_only")


def _get_setting_value(db: Session, key: str, default: str) -> str:
    row = db.query(Settings).filter(Settings.key == key).first()
    return (row.value or default).strip() if row and row.value else default


def _set_setting(db: Session, key: str, value: str, description: str):
    row = db.query(Settings).filter(Settings.key == key).first()
    if row:
        row.value = value
        if description:
            row.description = description
    else:
        db.add(Settings(key=key, value=value, description=description))
    db.commit()


# Min/max for screenshots per user per day (configurable)
SCREENSHOT_COUNT_PER_DAY_MIN = 1
SCREENSHOT_COUNT_PER_DAY_MAX = 50


@router.get("/screenshot-settings", response_model=dict)
def get_screenshot_settings(db: Session = Depends(get_db)):
    """Get user-usage screenshot settings: retention_days, visible_to, and count per user per day."""
    retention = _get_setting_value(db, "screenshot_retention_days", "7")
    visible_to = _get_setting_value(db, "screenshot_visible_to", "user_and_admin")
    count_per_day = _get_setting_value(db, "screenshot_count_per_user_per_day", "5")
    try:
        retention_days = int(retention)
    except ValueError:
        retention_days = 7
    if visible_to not in SCREENSHOT_VISIBLE_VALUES:
        visible_to = "user_and_admin"
    try:
        count_per_user_per_day = max(SCREENSHOT_COUNT_PER_DAY_MIN, min(SCREENSHOT_COUNT_PER_DAY_MAX, int(count_per_day)))
    except ValueError:
        count_per_user_per_day = 5
    return {
        "screenshot_retention_days": max(0, retention_days),
        "screenshot_visible_to": visible_to,
        "screenshot_count_per_user_per_day": count_per_user_per_day,
        "visible_to_options": list(SCREENSHOT_VISIBLE_VALUES),
        "screenshot_count_per_day_min": SCREENSHOT_COUNT_PER_DAY_MIN,
        "screenshot_count_per_day_max": SCREENSHOT_COUNT_PER_DAY_MAX,
        "description": {
            "screenshot_retention_days": "Delete screenshots older than this many days. 0 = never delete.",
            "screenshot_visible_to": "user_and_admin = user sees own, admin sees all; user_only = user sees own only; admin_only = only admin can view.",
            "screenshot_count_per_user_per_day": f"Max number of screenshots to take per user per day ({SCREENSHOT_COUNT_PER_DAY_MIN}-{SCREENSHOT_COUNT_PER_DAY_MAX}).",
        },
    }


class ScreenshotSettingsUpdate(BaseModel):
    retention_days: Optional[int] = None
    visible_to: Optional[str] = None
    count_per_user_per_day: Optional[int] = None


@router.post("/screenshot-settings")
def set_screenshot_settings(
    body: ScreenshotSettingsUpdate = Body(default=ScreenshotSettingsUpdate()),
    db: Session = Depends(get_db),
):
    """Set screenshot retention, visible_to, and/or count per user per day. Send JSON body with any of: retention_days, visible_to, count_per_user_per_day."""
    if body.retention_days is not None:
        retention_days = max(0, int(body.retention_days))
        _set_setting(
            db,
            "screenshot_retention_days",
            str(retention_days),
            "Delete user-usage screenshots older than this many days. 0 = never delete.",
        )
    if body.count_per_user_per_day is not None:
        count = max(SCREENSHOT_COUNT_PER_DAY_MIN, min(SCREENSHOT_COUNT_PER_DAY_MAX, int(body.count_per_user_per_day)))
        _set_setting(
            db,
            "screenshot_count_per_user_per_day",
            str(count),
            f"Max screenshots per user per day ({SCREENSHOT_COUNT_PER_DAY_MIN}-{SCREENSHOT_COUNT_PER_DAY_MAX}).",
        )
    if body.visible_to is not None:
        visible_to = body.visible_to.strip().lower()
        if visible_to not in SCREENSHOT_VISIBLE_VALUES:
            raise HTTPException(
                status_code=400,
                detail=f"visible_to must be one of: {', '.join(SCREENSHOT_VISIBLE_VALUES)}",
            )
        _set_setting(
            db,
            "screenshot_visible_to",
            visible_to,
            "Who can view screenshots: user_and_admin, user_only, or admin_only.",
        )
    return get_screenshot_settings(db)

