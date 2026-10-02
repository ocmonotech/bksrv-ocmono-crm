# routers/attendance.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import extract
from sqlalchemy.orm import joinedload
from database import get_db
from models.AttendanceModel import Attendance
from datetime import datetime, date
from routers.auth import get_current_user
from typing import Optional

router = APIRouter()


# Attendance Reports - Admin (month/year filter, with user joinedload)
@router.get("/admin/attendance")
def admin_attendance_report(
    month: int = date.today().month,
    year: int = date.today().year,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access denied")

    records = (
        db.query(Attendance)
        .options(joinedload(Attendance.user))
        .filter(extract("month", Attendance.date) == month)
        .filter(extract("year", Attendance.date) == year)
        .order_by(Attendance.date.desc())
        .all()
    )

    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        },
        "records": [
            {
                "id": r.id,
                "username": r.username,
                "date": r.date.isoformat() if r.date else None,
                "login_time": r.login_time.isoformat() if r.login_time else None,
                "logout_time": r.logout_time.isoformat() if r.logout_time else None
            }
            for r in records
        ],
        "month": month,
        "year": year
    }


@router.get("/admin/attendance-report")
def admin_attendance_report(
    month: Optional[int] = None,
    year: Optional[int] = None,
    username: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    today = datetime.today()
    selected_month = month or today.month
    selected_year = year or today.year

    # Compute date range
    start_date = datetime(selected_year, selected_month, 1)
    if selected_month == 12:
        end_date = datetime(selected_year + 1, 1, 1)
    else:
        end_date = datetime(selected_year, selected_month + 1, 1)
    
    # Build query with date filters
    query = db.query(Attendance).filter(
        Attendance.login_time >= start_date,
        Attendance.login_time < end_date
    )
    
    # Add username filter if provided
    if username:
        query = query.filter(Attendance.username == username)
    
    # Execute the query
    logs = query.order_by(Attendance.login_time.asc()).all()

    # Prepare data for JSON response
    attendance_logs = [
        {
            "username": log.username,
            "date": log.date.strftime("%d-%m-%Y") if log.date else None,
            "login_time": log.login_time.strftime("%H:%M:%S") if log.login_time else None,
            "logout_time": log.logout_time.strftime("%H:%M:%S") if log.logout_time else None,
            "total_hours": round((log.logout_time - log.login_time).total_seconds() / 3600, 2)
            if log.logout_time and log.login_time else None
        }
        for log in logs
    ]

    return {
        "month": selected_month,
        "year": selected_year,
        "attendance_logs": attendance_logs,
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        }
    }



# # Clock In
# @router.post("/attendance/clock-in")
# def clock_in(request: Request, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
#     today = date.today()

#     # Prevent multiple clock-ins
#     existing = db.query(Attendance).filter(Attendance.user_id == current_user.id, Attendance.date == today).first()
#     if existing:
#         return RedirectResponse(url="/attendance", status_code=303)

#     new_entry = Attendance(
#         user_id=current_user.id,
#         date=today,
#         clock_in=datetime.now().time(),
#         late=datetime.now().time() > datetime.strptime("10:30", "%H:%M").time()
#     )
#     db.add(new_entry)
#     db.commit()
#     return RedirectResponse(url="/attendance", status_code=303)

# # Clock Out
# @router.post("/attendance/clock-out")
# def clock_out(request: Request, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
#     today = date.today()
#     record = db.query(Attendance).filter(Attendance.user_id == current_user.id, Attendance.date == today).first()

#     if record and not record.clock_out:
#         record.clock_out = datetime.now().time()

#         # Calculate total hours
#         in_dt = datetime.combine(today, record.clock_in)
#         out_dt = datetime.combine(today, record.clock_out)
#         delta = out_dt - in_dt
#         record.total_hours = round(delta.total_seconds() / 3600, 2)

#         # Early leave check (e.g. < 8 hrs)
#         record.early_leave = record.total_hours < 8
#         db.commit()

#     return RedirectResponse(url="/attendance", status_code=303)
