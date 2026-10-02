# routers/leave.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.LeaveModel import LeaveRequest, LeaveBalance, Holiday
from models.UsersModel import User
from datetime import datetime
from routers.auth import get_current_user
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class LeaveApplyRequest(BaseModel):
    leave_type: str
    start_date: str
    end_date: str
    reason: str


class HolidayCreateRequest(BaseModel):
    holiday_date: str
    title: str
    description: Optional[str] = None


def update_leave_balance(db, user_id: int, leave_type: str, days: int):
    balance = db.query(LeaveBalance).filter(
        LeaveBalance.user_id == user_id,
        LeaveBalance.leave_type == leave_type
    ).first()

    if not balance:
        balance = LeaveBalance(user_id=user_id, leave_type=leave_type, total=12, used=0)  # default
        db.add(balance)

    balance.used += days
    db.commit()


# Balance Leaves
@router.get("/leave/balances")
def view_balances(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    balances = db.query(LeaveBalance).filter(LeaveBalance.user_id == current_user.id).all()
    
    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        },
        "balances": [
            {
                "id": b.id,
                "leave_type": b.leave_type,
                "total": b.total,
                "used": b.used,
                "remaining": b.total - b.used
            }
            for b in balances
        ]
    }


#Leave History
@router.get("/leave/history")
def leave_history_page(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    leaves = db.query(LeaveRequest).filter(LeaveRequest.user_id == current_user.id).order_by(LeaveRequest.applied_on.desc()).all()
    
    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        },
        "leaves": [
            {
                "id": leave.id,
                "leave_type": leave.leave_type,
                "start_date": leave.start_date.isoformat() if leave.start_date else None,
                "end_date": leave.end_date.isoformat() if leave.end_date else None,
                "reason": leave.reason,
                "status": leave.status,
                "applied_on": leave.applied_on.isoformat() if leave.applied_on else None
            }
            for leave in leaves
        ]
    }


#Apply for Leave
@router.post("/leave/apply")
def submit_leave(
    leave_data: LeaveApplyRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    leave = LeaveRequest(
        user_id=current_user.id,
        leave_type=leave_data.leave_type,
        start_date=datetime.strptime(leave_data.start_date, "%Y-%m-%d").date(),
        end_date=datetime.strptime(leave_data.end_date, "%Y-%m-%d").date(),
        reason=leave_data.reason
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)
    
    return {
        "message": "Leave application submitted successfully",
        "leave": {
            "id": leave.id,
            "leave_type": leave.leave_type,
            "start_date": leave.start_date.isoformat() if leave.start_date else None,
            "end_date": leave.end_date.isoformat() if leave.end_date else None,
            "reason": leave.reason,
            "status": leave.status
        }
    }


# Leave Reports - Admin
@router.get("/admin/leave-reports")
def leave_report_filter(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    employee_id: Optional[int] = None,
    leave_type: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None
):
    query = db.query(LeaveRequest)

    if employee_id:
        query = query.filter(LeaveRequest.user_id == employee_id)
    if leave_type:
        query = query.filter(LeaveRequest.leave_type == leave_type)
    if from_date and to_date:
        query = query.filter(LeaveRequest.start_date >= from_date, LeaveRequest.end_date <= to_date)

    leaves = query.order_by(LeaveRequest.applied_on.desc()).all()
    users = db.query(User).all()

    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        },
        "leaves": [
            {
                "id": l.id,
                "user_id": l.user_id,
                "leave_type": l.leave_type,
                "start_date": l.start_date.isoformat() if l.start_date else None,
                "end_date": l.end_date.isoformat() if l.end_date else None,
                "reason": l.reason,
                "status": l.status,
                "applied_on": l.applied_on.isoformat() if l.applied_on else None
            }
            for l in leaves
        ],
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "first_name": u.first_name,
                "last_name": u.last_name
            }
            for u in users
        ],
        "filters": {
            "employee_id": employee_id,
            "leave_type": leave_type,
            "from_date": from_date,
            "to_date": to_date
        }
    }


# Leave Requests - Admin
@router.get("/admin/leave-requests")
def admin_leave_panel(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access denied")

    leaves = db.query(LeaveRequest).order_by(LeaveRequest.applied_on.desc()).all()

    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        },
        "leaves": [
            {
                "id": l.id,
                "user_id": l.user_id,
                "leave_type": l.leave_type,
                "start_date": l.start_date.isoformat() if l.start_date else None,
                "end_date": l.end_date.isoformat() if l.end_date else None,
                "reason": l.reason,
                "status": l.status,
                "applied_on": l.applied_on.isoformat() if l.applied_on else None
            }
            for l in leaves
        ]
    }


# Approve Leave
@router.post("/admin/leave-requests/{leave_id}/approve")
def approve_leave(leave_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access denied")

    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave request not found")

    if leave.status == "Pending":
        leave.status = "Approved"
        days = (leave.end_date - leave.start_date).days + 1
        update_leave_balance(db, leave.user_id, leave.leave_type, days)
        db.commit()

    return {"message": "Leave approved successfully", "leave_id": leave_id}


# Reject Leave
@router.post("/admin/leave-requests/{leave_id}/reject")
def reject_leave(leave_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access denied")

    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave request not found")

    leave.status = "Rejected"
    db.commit()

    return {"message": "Leave rejected successfully", "leave_id": leave_id}


@router.get("/admin/holidays")
def list_holidays(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Holiday)
    if year:
        from datetime import date
        from calendar import monthrange

        if month:
            start = date(year, month, 1)
            end = date(year, month, monthrange(year, month)[1])
        else:
            start = date(year, 1, 1)
            end = date(year, 12, 31)
        query = query.filter(Holiday.holiday_date >= start, Holiday.holiday_date <= end)

    rows = query.order_by(Holiday.holiday_date.asc()).all()
    return {
        "holidays": [
            {
                "id": h.id,
                "holiday_date": h.holiday_date.isoformat(),
                "title": h.title,
                "description": h.description,
                "created_by_username": h.created_by_username,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in rows
        ]
    }


@router.post("/admin/holidays")
def create_holiday(
    payload: HolidayCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        holiday_date = datetime.strptime(payload.holiday_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="holiday_date must be YYYY-MM-DD")

    existing = db.query(Holiday).filter(Holiday.holiday_date == holiday_date).first()
    if existing:
        raise HTTPException(status_code=400, detail="Holiday already exists for this date")

    row = Holiday(
        holiday_date=holiday_date,
        title=payload.title.strip(),
        description=(payload.description or "").strip() or None,
        created_by_username=current_user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "message": "Holiday created",
        "holiday": {
            "id": row.id,
            "holiday_date": row.holiday_date.isoformat(),
            "title": row.title,
            "description": row.description,
        },
    }


@router.delete("/admin/holidays/{holiday_id}")
def delete_holiday(
    holiday_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access denied")
    row = db.query(Holiday).filter(Holiday.id == holiday_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Holiday not found")
    db.delete(row)
    db.commit()
    return {"message": "Holiday deleted", "holiday_id": holiday_id}
