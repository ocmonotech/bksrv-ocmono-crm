"""API for reporting and viewing user PC usage: screen time, bandwidth, running apps, application usage."""
import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from routers.auth import get_current_user
from models.UsersModel import User
from models.UserUsageModel import UserUsageSnapshot, UserApplicationUsage, UserUsageScreenshot
from models.SettingsModel import Settings
from datetime import datetime, date, timedelta
from utils.datetime_utils import ist_now
from typing import Optional, List
from pydantic import BaseModel

router = APIRouter(prefix="/user-usage", tags=["User Usage"])

# Base directory for storing screenshots (relative to project root). Create if missing.
SCREENSHOTS_BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", "user_screenshots")

# Allowed values for screenshot_visible_to setting
SCREENSHOT_VISIBLE_VALUES = ("user_and_admin", "user_only", "admin_only")


def _get_screenshot_settings(db: Session) -> dict:
    """Return screenshot_retention_days, screenshot_visible_to, and screenshot_count_per_user_per_day."""
    def get_val(key: str, default: str) -> str:
        row = db.query(Settings).filter(Settings.key == key).first()
        return (row.value or default).strip() if row and row.value else default
    retention = get_val("screenshot_retention_days", "7")
    visible_to = get_val("screenshot_visible_to", "user_and_admin")
    count_per_day = get_val("screenshot_count_per_user_per_day", "5")
    try:
        retention_days = max(0, int(retention))
    except ValueError:
        retention_days = 7
    if visible_to not in SCREENSHOT_VISIBLE_VALUES:
        visible_to = "user_and_admin"
    try:
        count_per_user_per_day = max(1, min(50, int(count_per_day)))
    except ValueError:
        count_per_user_per_day = 5
    return {
        "screenshot_retention_days": retention_days,
        "screenshot_visible_to": visible_to,
        "screenshot_count_per_user_per_day": count_per_user_per_day,
    }


# --- Schemas ---
class SnapshotCreate(BaseModel):
    reported_at: Optional[datetime] = None
    screen_active_seconds: int = 0  # Total screen visible/on time (overall, not per-app)
    mouse_active_seconds: int = 0   # Mouse/keyboard active = time user was actively working on PC
    bandwidth_received_bytes: int = 0
    bandwidth_sent_bytes: int = 0
    applications_running_count: int = 0


class ApplicationUsageItem(BaseModel):
    application_name: str
    usage_seconds: int


class ApplicationsReportCreate(BaseModel):
    reported_at: Optional[datetime] = None
    applications: List[ApplicationUsageItem] = []


# --- POST: client reports snapshot (desktop agent calls this) ---
@router.post("/snapshot")
def report_snapshot(
    body: SnapshotCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Report a usage snapshot: screen active time, bandwidth, running app count. Admin usage is not stored."""
    if getattr(current_user, "role", None) == "Admin":
        return {"message": "Snapshot not stored (admin usage not tracked)", "id": None}
    reported_at = body.reported_at or ist_now()
    snap = UserUsageSnapshot(
        user_id=current_user.id,
        reported_at=reported_at,
        screen_active_seconds=max(0, body.screen_active_seconds),
        mouse_active_seconds=max(0, body.mouse_active_seconds),
        bandwidth_received_bytes=max(0, body.bandwidth_received_bytes),
        bandwidth_sent_bytes=max(0, body.bandwidth_sent_bytes),
        applications_running_count=max(0, body.applications_running_count),
    )
    db.add(snap)
    db.commit()
    return {"message": "Snapshot recorded", "id": snap.id}


# --- POST: client reports application usage list ---
@router.post("/applications")
def report_applications(
    body: ApplicationsReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Report per-application usage (e.g. Chrome 1200s, Code 600s). Admin usage is not stored."""
    if getattr(current_user, "role", None) == "Admin":
        return {"message": "Application usage not stored (admin usage not tracked)", "count": 0}
    reported_at = body.reported_at or ist_now()
    for item in body.applications:
        if not item.application_name or item.usage_seconds <= 0:
            continue
        usage = UserApplicationUsage(
            user_id=current_user.id,
            reported_at=reported_at,
            application_name=item.application_name[:255],
            usage_seconds=item.usage_seconds,
        )
        db.add(usage)
    db.commit()
    return {"message": "Application usage recorded", "count": len(body.applications)}


# --- Screenshots: 5 random per user per day (desktop app uploads) ---
def _screenshots_dir_for_user(user_id: int, day: date) -> str:
    """Directory for a user's screenshots on a given day. Creates if missing."""
    sub = os.path.join(str(user_id), day.isoformat())
    path = os.path.join(SCREENSHOTS_BASE_DIR, sub)
    os.makedirs(path, exist_ok=True)
    return path


@router.post("/screenshot")
def upload_screenshot(
    file: UploadFile = File(...),
    captured_at: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload one screenshot. Max per user per day from settings (default 5). Admin usage is not stored."""
    if getattr(current_user, "role", None) == "Admin":
        return {"message": "Screenshot not stored (admin usage not tracked)", "id": None}
    opts = _get_screenshot_settings(db)
    max_per_day = opts["screenshot_count_per_user_per_day"]
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00")) if captured_at else ist_now()
    except (ValueError, AttributeError):
        captured = ist_now()
    day = captured.date() if hasattr(captured, "date") else date.today()

    # Enforce max per user per day (from settings)
    count = (
        db.query(UserUsageScreenshot.id)
        .filter(
            UserUsageScreenshot.user_id == current_user.id,
            func.date(UserUsageScreenshot.captured_at) == day,
        )
        .count()
    )
    if count >= max_per_day:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {max_per_day} screenshots per user per day already reached for {day}.",
        )

    # Allowed content types
    if file.content_type and file.content_type not in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
        raise HTTPException(status_code=400, detail="Only image files (png, jpeg, webp) are allowed.")

    ext = "png"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower() or "png"
    if ext not in ("png", "jpg", "jpeg", "webp"):
        ext = "png"

    dir_path = _screenshots_dir_for_user(current_user.id, day)
    filename = f"{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join(dir_path, filename)
    rel_path = os.path.join(str(current_user.id), day.isoformat(), filename).replace("\\", "/")

    try:
        contents = file.file.read()
        if len(contents) > 5 * 1024 * 1024:  # 5 MB max
            raise HTTPException(status_code=400, detail="Screenshot file too large (max 5 MB).")
        with open(file_path, "wb") as f:
            f.write(contents)
    finally:
        file.file.close()

    record = UserUsageScreenshot(
        user_id=current_user.id,
        captured_at=captured,
        file_path=rel_path,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "message": "Screenshot saved",
        "id": record.id,
        "captured_at": captured.isoformat(),
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.get("/screenshots")
def list_my_screenshots(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List current user's screenshots in date range. Respects screenshot_visible_to and retention settings."""
    opts = _get_screenshot_settings(db)
    if opts["screenshot_visible_to"] == "admin_only" and getattr(current_user, "role", None) != "Admin":
        raise HTTPException(status_code=403, detail="Screenshot viewing is restricted to admins only")
    to_date = to_date or date.today()
    from_date = from_date or (to_date - timedelta(days=7))
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    retention_days = opts["screenshot_retention_days"]
    if retention_days > 0:
        cutoff = to_date - timedelta(days=retention_days)
        if from_date < cutoff:
            from_date = cutoff

    rows = (
        db.query(UserUsageScreenshot)
        .filter(
            UserUsageScreenshot.user_id == current_user.id,
            func.date(UserUsageScreenshot.captured_at) >= from_date,
            func.date(UserUsageScreenshot.captured_at) <= to_date,
        )
        .order_by(UserUsageScreenshot.captured_at.desc())
        .all()
    )
    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "screenshots": [
            {
                "id": r.id,
                "captured_at": r.captured_at.isoformat() if r.captured_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "url": f"/user-usage/screenshots/{r.id}/image",
            }
            for r in rows
        ],
    }


@router.get("/screenshots/admin")
def list_screenshots_admin(
    user_id: Optional[int] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List screenshots by user/date. Admin only. Respects screenshot_visible_to (user_only = admin cannot list) and retention."""
    if getattr(current_user, "role", None) != "Admin":
        raise HTTPException(status_code=403, detail="Admin only")
    opts = _get_screenshot_settings(db)
    if opts["screenshot_visible_to"] == "user_only":
        raise HTTPException(status_code=403, detail="Screenshot viewing is set to user_only; admin cannot view others' screenshots")
    query = db.query(UserUsageScreenshot).order_by(UserUsageScreenshot.captured_at.desc())
    if user_id is not None:
        query = query.filter(UserUsageScreenshot.user_id == user_id)
    if from_date is not None:
        query = query.filter(func.date(UserUsageScreenshot.captured_at) >= from_date)
    if to_date is not None:
        query = query.filter(func.date(UserUsageScreenshot.captured_at) <= to_date)
    retention_days = opts["screenshot_retention_days"]
    if retention_days > 0:
        cutoff = date.today() - timedelta(days=retention_days)
        query = query.filter(func.date(UserUsageScreenshot.captured_at) >= cutoff)
    rows = query.limit(500).all()
    return {
        "screenshots": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "captured_at": r.captured_at.isoformat() if r.captured_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "url": f"/user-usage/screenshots/{r.id}/image",
            }
            for r in rows
        ],
    }


@router.get("/screenshots/{screenshot_id}/image")
def get_screenshot_image(
    screenshot_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Serve screenshot image. Respects screenshot_visible_to setting."""
    opts = _get_screenshot_settings(db)
    visible_to = opts["screenshot_visible_to"]
    is_admin = getattr(current_user, "role", None) == "Admin"
    if visible_to == "admin_only" and not is_admin:
        raise HTTPException(status_code=403, detail="Screenshot viewing is restricted to admins only")
    record = db.query(UserUsageScreenshot).filter(UserUsageScreenshot.id == screenshot_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    if record.user_id != current_user.id:
        if not is_admin:
            raise HTTPException(status_code=403, detail="Not allowed to view this screenshot")
        if visible_to == "user_only":
            raise HTTPException(status_code=403, detail="Screenshot viewing is set to user_only; admin cannot view others' screenshots")
    full_path = os.path.join(SCREENSHOTS_BASE_DIR, record.file_path)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Screenshot file not found")
    return FileResponse(full_path, media_type="image/png")


@router.post("/screenshots/cleanup")
def cleanup_old_screenshots(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete screenshots older than retention_days (from settings). Admin only. Removes DB rows and files from disk."""
    if getattr(current_user, "role", None) != "Admin":
        raise HTTPException(status_code=403, detail="Admin only")
    opts = _get_screenshot_settings(db)
    retention_days = opts["screenshot_retention_days"]
    if retention_days <= 0:
        return {"message": "Screenshot retention is set to never delete (0). No cleanup performed.", "deleted": 0}
    cutoff = ist_now() - timedelta(days=retention_days)
    old = db.query(UserUsageScreenshot).filter(UserUsageScreenshot.captured_at < cutoff).all()
    deleted = 0
    for record in old:
        full_path = os.path.join(SCREENSHOTS_BASE_DIR, record.file_path)
        if os.path.isfile(full_path):
            try:
                os.remove(full_path)
            except OSError:
                pass
        db.delete(record)
        deleted += 1
    db.commit()
    return {"message": f"Deleted {deleted} screenshot(s) older than {retention_days} days", "deleted": deleted}


# --- GET: current user's usage in date range (aggregated) ---
@router.get("/me")
def get_my_usage(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get aggregated usage for the current user. Defaults to last 7 days."""
    to_date = to_date or date.today()
    from_date = from_date or (to_date - timedelta(days=7))
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    # Snapshots in range: totals
    q = (
        db.query(
            func.sum(UserUsageSnapshot.screen_active_seconds).label("screen_active_seconds"),
            func.sum(UserUsageSnapshot.mouse_active_seconds).label("mouse_active_seconds"),
            func.sum(UserUsageSnapshot.bandwidth_received_bytes).label("bandwidth_received_bytes"),
            func.sum(UserUsageSnapshot.bandwidth_sent_bytes).label("bandwidth_sent_bytes"),
            func.avg(UserUsageSnapshot.applications_running_count).label("avg_apps_running"),
        )
        .filter(
            UserUsageSnapshot.user_id == current_user.id,
            func.date(UserUsageSnapshot.reported_at) >= from_date,
            func.date(UserUsageSnapshot.reported_at) <= to_date,
        )
    )
    row = q.first()
    # Per-day breakdown
    daily = (
        db.query(
            func.date(UserUsageSnapshot.reported_at).label("day"),
            func.sum(UserUsageSnapshot.screen_active_seconds).label("screen_active_seconds"),
            func.sum(UserUsageSnapshot.mouse_active_seconds).label("mouse_active_seconds"),
            func.sum(UserUsageSnapshot.bandwidth_received_bytes).label("bandwidth_received_bytes"),
            func.sum(UserUsageSnapshot.bandwidth_sent_bytes).label("bandwidth_sent_bytes"),
            func.avg(UserUsageSnapshot.applications_running_count).label("avg_apps_running"),
        )
        .filter(
            UserUsageSnapshot.user_id == current_user.id,
            func.date(UserUsageSnapshot.reported_at) >= from_date,
            func.date(UserUsageSnapshot.reported_at) <= to_date,
        )
        .group_by(func.date(UserUsageSnapshot.reported_at))
        .order_by(func.date(UserUsageSnapshot.reported_at))
        .all()
    )
    # Top applications in range (by total usage_seconds)
    top_apps = (
        db.query(
            UserApplicationUsage.application_name,
            func.sum(UserApplicationUsage.usage_seconds).label("total_seconds"),
        )
        .filter(
            UserApplicationUsage.user_id == current_user.id,
            func.date(UserApplicationUsage.reported_at) >= from_date,
            func.date(UserApplicationUsage.reported_at) <= to_date,
        )
        .group_by(UserApplicationUsage.application_name)
        .order_by(func.sum(UserApplicationUsage.usage_seconds).desc())
        .limit(20)
        .all()
    )

    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "summary": {
            "screen_active_seconds": row.screen_active_seconds or 0,
            "mouse_active_seconds": row.mouse_active_seconds or 0,
            "bandwidth_received_bytes": row.bandwidth_received_bytes or 0,
            "bandwidth_sent_bytes": row.bandwidth_sent_bytes or 0,
            "avg_applications_running": round(float(row.avg_apps_running or 0), 1),
        },
        "summary_labels": {
            "screen_active_seconds": "Total screen visible time (seconds)",
            "mouse_active_seconds": "Mouse/keyboard active – time worked on PC (seconds)",
            "top_applications": "Apps used (name and time in seconds)",
        },
        "by_day": [
            {
                "day": d.day.isoformat(),
                "screen_active_seconds": d.screen_active_seconds or 0,
                "mouse_active_seconds": d.mouse_active_seconds or 0,
                "bandwidth_received_bytes": d.bandwidth_received_bytes or 0,
                "bandwidth_sent_bytes": d.bandwidth_sent_bytes or 0,
                "avg_apps_running": round(float(d.avg_apps_running or 0), 1),
            }
            for d in daily
        ],
        "top_applications": [
            {"application_name": a.application_name, "total_seconds": a.total_seconds}
            for a in top_apps
        ],
    }


# --- GET: admin report (all users) - optional, only if you have admin check ---
def _is_admin(user: User) -> bool:
    return getattr(user, "role", None) == "Admin"


@router.get("/report")
def get_usage_report(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get usage report for all users (Admin only)."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin only")
    to_date = to_date or date.today()
    from_date = from_date or (to_date - timedelta(days=7))
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    per_user = (
        db.query(
            UserUsageSnapshot.user_id,
            User.username,
            func.sum(UserUsageSnapshot.screen_active_seconds).label("screen_active_seconds"),
            func.sum(UserUsageSnapshot.mouse_active_seconds).label("mouse_active_seconds"),
            func.sum(UserUsageSnapshot.bandwidth_received_bytes).label("bandwidth_received_bytes"),
            func.sum(UserUsageSnapshot.bandwidth_sent_bytes).label("bandwidth_sent_bytes"),
            func.avg(UserUsageSnapshot.applications_running_count).label("avg_apps_running"),
        )
        .join(User, User.id == UserUsageSnapshot.user_id)
        .filter(
            func.date(UserUsageSnapshot.reported_at) >= from_date,
            func.date(UserUsageSnapshot.reported_at) <= to_date,
        )
        .group_by(UserUsageSnapshot.user_id, User.username)
        .all()
    )
    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "users": [
            {
                "user_id": u.user_id,
                "username": u.username,
                "screen_active_seconds": u.screen_active_seconds or 0,
                "mouse_active_seconds": u.mouse_active_seconds or 0,
                "bandwidth_received_bytes": u.bandwidth_received_bytes or 0,
                "bandwidth_sent_bytes": u.bandwidth_sent_bytes or 0,
                "avg_applications_running": round(float(u.avg_apps_running or 0), 1),
            }
            for u in per_user
        ],
    }
