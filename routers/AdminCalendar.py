from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, date
from database import get_db
from models.ProjectTimerModel import ProjectTimer
from models.LeaveModel import LeaveRequest
from routers.auth import get_current_user


router = APIRouter()

@router.get("/admin-calendar-events")
def get_admin_calendar_events(db: Session = Depends(get_db)):
    today = date.today()
    events = []

    # 1. Employee Time Logs
    logs = db.query(ProjectTimer).all()
    for log in logs:
        if log.start_time and log.end_time:
            events.append({
                "title": f"{log.username} - {log.project_code}",
                "start": log.start_time.isoformat(),
                "end": log.end_time.isoformat(),
                "color": "#198754"  # Green
            })

    # 2. Who is on Leave Today
    leaves = db.query(LeaveRequest).filter(
        Leave.start_date <= today,
        Leave.end_date >= today
    ).all()
    for leave in leaves:
        events.append({
            "title": f"On Leave: {leave.username}",
            "start": today.isoformat(),
            "color": "#ffc107"  # Yellow
        })

    # 3. Today's Worked Projects
    today_logs = db.query(ProjectTimer).filter(
        TimeLog.start_time >= datetime.combine(today, datetime.min.time())
    ).all()
    for tlog in today_logs:
        events.append({
            "title": f"Worked: {tlog.project_code}",
            "start": tlog.start_time.isoformat(),
            "end": tlog.end_time.isoformat() if tlog.end_time else None,
            "color": "#0d6efd"  # Blue
        })

    return events
