"""
Upload punch-machine exports (CSV / XLSX / XLS Tabulator reports), store punches, and build monthly reports:
late marks, half-days, approved leave days, weekday absences.
"""

from __future__ import annotations

import json
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from models.LeaveModel import LeaveRequest, Holiday
from models.NotificationModel import Notification
from models.PunchMachineModel import (
    PunchMachineExceptionDay,
    PunchMachineImport,
    PunchMachinePunch,
    PunchMachineScheduleDay,
)
from models.UsersModel import User
from routers.LeadImport import MAX_FILE_SIZE, parse_file_content
from routers.auth import get_current_user
from routers.AttendanceSettings import settings_to_dict
from utils.attendance_time_rules import compute_day_metrics
from utils.attendance_settings_db import get_or_create_settings
from utils.punch_machine_excel_reports import ParsedMachineUpload, try_parse_tabulator_workbook
from utils.punch_machine_parse import (
    extract_username_and_punch,
    normalize_row,
    resolve_username,
    resolve_username_with_note,
    row_to_debug_json,
)

router = APIRouter(tags=["Punch Machine Attendance"])


def _require_admin(current_user: User) -> None:
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access denied")


def _file_type(filename: str) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".xlsx"):
        return "xlsx"
    if lower.endswith(".xls"):
        return "xls"
    raise HTTPException(status_code=400, detail="Unsupported file type. Use .csv, .xlsx, or .xls")


def _daterange_month(year: int, month: int) -> Tuple[date, date]:
    last = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _weekday(d: date) -> int:
    return d.weekday()


def _leave_dates_set(db: Session, user_id: int, month_start: date, month_end: date) -> set[date]:
    leaves = (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.user_id == user_id,
            LeaveRequest.status == "Approved",
            LeaveRequest.start_date <= month_end,
            LeaveRequest.end_date >= month_start,
        )
        .all()
    )
    days: set[date] = set()
    for lv in leaves:
        sd = max(lv.start_date, month_start)
        ed = min(lv.end_date, month_end)
        cur = sd
        while cur <= ed:
            days.add(cur)
            cur += timedelta(days=1)
    return days


def _holiday_dates_set(db: Session, month_start: date, month_end: date) -> set[date]:
    rows = (
        db.query(Holiday)
        .filter(
            Holiday.holiday_date >= month_start,
            Holiday.holiday_date <= month_end,
        )
        .all()
    )
    return {h.holiday_date for h in rows}


def _persist_parsed_tabulator(
    db: Session,
    batch: PunchMachineImport,
    parsed: ParsedMachineUpload,
    users: List[User],
    reasons: List[str],
    affected_usernames: set[str],
) -> Tuple[int, int]:
    """Insert punches, schedule rows, exception rows, statistics. Returns (imported, skipped)."""
    imported = 0
    skipped = 0
    seen_punch: set[Tuple[str, str]] = set()

    for raw_user, punch_at, note in parsed.punches:
        uname, err = resolve_username_with_note(raw_user, users, note)
        if not uname:
            skipped += 1
            if len(reasons) < 15:
                reasons.append(err or f"unresolved user for punch {raw_user}")
            continue
        key = (uname, punch_at.strftime("%Y-%m-%d %H:%M:%S"))
        if key in seen_punch:
            continue
        seen_punch.add(key)
        db.add(
            PunchMachinePunch(
                import_id=batch.id,
                username=uname,
                punch_at=punch_at,
                raw_row=note[:2000] if note else None,
            )
        )
        affected_usernames.add(uname)
        imported += 1

    for row in parsed.schedule_days:
        mk = str(row.get("machine_user_key") or "").strip()
        disp = str(row.get("display_name") or "").strip()
        uname, _ = resolve_username(mk, users)
        if not uname and disp:
            uname, _ = resolve_username(disp, users)
        try:
            wd = date.fromisoformat(str(row["work_date"]))
        except (ValueError, TypeError, KeyError):
            skipped += 1
            continue
        code = row.get("code")
        code_s = str(code).strip() if code is not None else None
        db.add(
            PunchMachineScheduleDay(
                import_id=batch.id,
                machine_user_key=mk or disp or "?",
                username=uname,
                work_date=wd,
                code=code_s,
            )
        )

    for row in parsed.exception_days:
        mk = str(row.get("machine_user_key") or "").strip()
        disp = str(row.get("display_name") or "").strip()
        uname, _ = resolve_username(mk, users)
        if not uname and disp:
            uname, _ = resolve_username(disp, users)
        try:
            wd = date.fromisoformat(str(row["work_date"]))
        except (ValueError, TypeError, KeyError):
            skipped += 1
            continue
        db.add(
            PunchMachineExceptionDay(
                import_id=batch.id,
                machine_user_key=mk or disp or "?",
                username=uname,
                work_date=wd,
                late_min=row.get("late_min"),
                early_min=row.get("early_min"),
                absence_min=row.get("absence_min"),
                total_min=row.get("total_min"),
                raw_json=json.dumps(row, default=str)[:2000],
            )
        )

    if parsed.statistics_rows:
        batch.statistics_json = json.dumps(parsed.statistics_rows, default=str)

    return imported, skipped


@router.post("/admin/punch-machine/upload")
async def upload_punch_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    ftype = _file_type(file.filename or "")
    users = db.query(User).filter(User.is_deleted == False).all()
    user_by_username = {u.username: u for u in users}
    imported = 0
    skipped = 0
    reasons: List[str] = []
    affected_usernames: set[str] = set()

    batch = PunchMachineImport(
        filename=file.filename or "upload",
        imported_by_user_id=current_user.id,
        imported_by_username=current_user.username,
        rows_imported=0,
        rows_skipped=0,
    )
    db.add(batch)
    db.flush()

    parsed: Optional[ParsedMachineUpload] = None
    if ftype in ("xlsx", "xls"):
        try:
            parsed = try_parse_tabulator_workbook(content, file.filename or "")
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Could not read Excel file: {e}. For .xls, ensure xlrd is installed; or save as .xlsx.",
            ) from e

    if parsed and parsed.format_name != "unknown":
        batch.detected_format = parsed.format_name
        batch.report_year = parsed.report_year
        batch.report_month = parsed.report_month
        imported, skipped = _persist_parsed_tabulator(
            db, batch, parsed, users, reasons, affected_usernames
        )
    else:
        if ftype == "xls":
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail="This .xls layout was not recognized. Use 'Statistical Report of Attendance' / other Tabulator exports, or save as .xlsx / .csv.",
            )
        try:
            rows = parse_file_content(content, ftype)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not read file: {e}") from e

        batch.detected_format = "tabular_rows"
        for raw in rows:
            if not isinstance(raw, dict):
                skipped += 1
                if len(reasons) < 15:
                    reasons.append("row is not a dict")
                continue
            norm = normalize_row(raw)
            raw_id, punch_at = extract_username_and_punch(norm)
            if not raw_id or not punch_at:
                skipped += 1
                if len(reasons) < 15:
                    reasons.append(f"missing user or datetime: {row_to_debug_json(norm)[:120]}")
                continue
            uname, err = resolve_username(raw_id, users)
            if not uname:
                skipped += 1
                if len(reasons) < 15:
                    reasons.append(err or "unresolved user")
                continue
            db.add(
                PunchMachinePunch(
                    import_id=batch.id,
                    username=uname,
                    punch_at=punch_at,
                    raw_row=row_to_debug_json(norm),
                )
            )
            affected_usernames.add(uname)
            imported += 1

    # Notify affected employees that new attendance data is available.
    notif_month = batch.report_month or None
    notif_year = batch.report_year or None
    for uname in sorted(affected_usernames):
        u = user_by_username.get(uname)
        if not u:
            continue
        if notif_month and notif_year:
            message = (
                f"Your attendance for {notif_month:02d}-{notif_year} has been updated. "
                "Please review your report."
            )
            target_url = f"/attendance/my-report?month={notif_month}&year={notif_year}"
        else:
            message = "Your attendance has been updated. Please review your report."
            target_url = "/attendance/my-report"
        db.add(
            Notification(
                user_id=u.id,
                message=message,
                type="attendance",
                target_url=target_url,
                entity_id=batch.id,
            )
        )

    batch.rows_imported = imported
    batch.rows_skipped = skipped
    batch.skip_reasons_sample = json.dumps(reasons[:15]) if reasons else None
    db.commit()
    db.refresh(batch)

    out: Dict[str, Any] = {
        "import_id": batch.id,
        "filename": batch.filename,
        "detected_format": batch.detected_format,
        "report_year": batch.report_year,
        "report_month": batch.report_month,
        "punches_stored": imported,
        "rows_imported": imported,
        "rows_skipped": skipped,
        "skip_reasons_sample": reasons[:15],
        "statistics_row_count": len(json.loads(batch.statistics_json)) if batch.statistics_json else 0,
    }
    if parsed:
        out["schedule_days_stored"] = len(parsed.schedule_days)
        out["exception_days_stored"] = len(parsed.exception_days)
    return out


@router.get("/admin/punch-machine/imports")
def list_punch_imports(
    limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    q = db.query(PunchMachineImport).order_by(PunchMachineImport.id.desc()).limit(limit).all()
    return {
        "imports": [
            {
                "id": b.id,
                "filename": b.filename,
                "imported_at": b.imported_at.isoformat() if b.imported_at else None,
                "imported_by": b.imported_by_username,
                "detected_format": b.detected_format,
                "report_year": b.report_year,
                "report_month": b.report_month,
                "rows_imported": b.rows_imported,
                "rows_skipped": b.rows_skipped,
            }
            for b in q
        ]
    }


def _latest_by_import(
    rows: List[Any], key_fn
) -> Dict[Any, Any]:
    best: Dict[Any, Any] = {}
    for r in rows:
        k = key_fn(r)
        if k is None:
            continue
        cur = best.get(k)
        if cur is None or r.import_id > cur.import_id:
            best[k] = r
    return best


@router.get("/admin/punch-machine/report")
def punch_machine_report(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000, le=2100),
    username: Optional[str] = Query(None, description="Filter to one employee username"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return _build_punch_report(db, month, year, username, current_user)


@router.get("/attendance/my-report")
def my_attendance_report(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Self-service report for logged-in user only (employee/admin sees their own attendance only).
    """
    return _build_punch_report(db, month, year, current_user.username, current_user)


def _build_punch_report(
    db: Session,
    month: int,
    year: int,
    username: Optional[str],
    current_user: User,
) -> Dict[str, Any]:
    """
    Monthly report from stored punch rows plus Schedule / Exception / Statistical imports for that month.
    Late marks, half-days (per first/second duty window), and overtime use attendance settings.
    """
    att_settings = get_or_create_settings(db)
    month_start, month_end = _daterange_month(year, month)
    holiday_days_set = _holiday_dates_set(db, month_start, month_end)
    start_dt = datetime.combine(month_start, time.min)
    end_dt = datetime.combine(month_end + timedelta(days=1), time.min)

    punch_q = db.query(PunchMachinePunch).filter(
        PunchMachinePunch.punch_at >= start_dt,
        PunchMachinePunch.punch_at < end_dt,
    )
    if username:
        punch_q = punch_q.filter(PunchMachinePunch.username == username)
    punches = punch_q.order_by(PunchMachinePunch.punch_at.asc()).all()

    by_user_day: Dict[str, Dict[date, List[datetime]]] = defaultdict(lambda: defaultdict(list))
    for p in punches:
        d = p.punch_at.date()
        by_user_day[p.username][d].append(p.punch_at)

    user_q = db.query(User).filter(User.is_deleted == False, User.role == "Employee")
    if username:
        user_q = user_q.filter(User.username == username)
    employees = user_q.all()
    user_by_username = {u.username: u for u in employees}

    sch_q = db.query(PunchMachineScheduleDay).filter(
        PunchMachineScheduleDay.work_date >= month_start,
        PunchMachineScheduleDay.work_date <= month_end,
    )
    if username:
        sch_q = sch_q.filter(PunchMachineScheduleDay.username == username)
    schedule_latest = _latest_by_import(
        sch_q.all(),
        lambda r: (r.username, r.work_date) if r.username else None,
    )

    ex_q = db.query(PunchMachineExceptionDay).filter(
        PunchMachineExceptionDay.work_date >= month_start,
        PunchMachineExceptionDay.work_date <= month_end,
    )
    if username:
        ex_q = ex_q.filter(PunchMachineExceptionDay.username == username)
    exception_latest = _latest_by_import(
        ex_q.all(),
        lambda r: (r.username, r.work_date) if r.username else None,
    )

    stat_imports = (
        db.query(PunchMachineImport)
        .filter(
            PunchMachineImport.report_year == year,
            PunchMachineImport.report_month == month,
            PunchMachineImport.statistics_json.isnot(None),
        )
        .order_by(PunchMachineImport.id.desc())
        .all()
    )
    machine_statistics: List[Dict[str, Any]] = []
    for imp in stat_imports:
        try:
            rows = json.loads(imp.statistics_json)
        except (json.JSONDecodeError, TypeError):
            rows = []
        machine_statistics.append(
            {
                "import_id": imp.id,
                "filename": imp.filename,
                "imported_at": imp.imported_at.isoformat() if imp.imported_at else None,
                "rows": rows,
            }
        )

    daily_rows: List[Dict[str, Any]] = []
    summary_by_user: Dict[str, Dict[str, Any]] = {}

    def ensure_summary(uname: str) -> Dict[str, Any]:
        if uname not in summary_by_user:
            summary_by_user[uname] = {
                "username": uname,
                "late_marks": 0,
                "half_days": 0,
                "leave_days": 0,
                "absent_days": 0,
                "present_days": 0,
                "total_ot_checkin_minutes": 0,
                "total_ot_checkout_minutes": 0,
            }
        return summary_by_user[uname]

    all_usernames = set(by_user_day.keys()) | set(user_by_username.keys())
    for uname in sorted(all_usernames):
        u = user_by_username.get(uname)
        leave_days_set = _leave_dates_set(db, u.id, month_start, month_end) if u else set()
        if u:
            ensure_summary(uname)["leave_days"] = len(leave_days_set)

        cur = month_start
        while cur <= month_end:
            wd = _weekday(cur)
            is_weekend = wd >= 5
            day_punches = sorted(by_user_day.get(uname, {}).get(cur, []))

            if is_weekend and not day_punches:
                cur += timedelta(days=1)
                continue

            on_leave = cur in leave_days_set
            on_holiday = cur in holiday_days_set
            first = day_punches[0] if day_punches else None
            last = day_punches[-1] if day_punches else None

            present = bool(day_punches)
            late = False
            half_day = False
            hours_worked: Optional[float] = None
            hours_morning: Optional[float] = None
            hours_afternoon: Optional[float] = None
            first_half_short = False
            second_half_short = False
            ot_in = 0
            ot_out = 0

            if present and first and last:
                m = compute_day_metrics(day_punches, cur, att_settings)
                late = m.late
                half_day = m.half_day
                hours_worked = m.hours_total_span
                hours_morning = m.hours_morning
                hours_afternoon = m.hours_afternoon
                first_half_short = m.first_half_short
                second_half_short = m.second_half_short
                ot_in = m.ot_checkin_minutes
                ot_out = m.ot_checkout_minutes

            absent = (
                not is_weekend
                and not present
                and not on_leave
                and not on_holiday
                and u is not None
            )

            if present:
                ensure_summary(uname)["present_days"] += 1
                if late:
                    ensure_summary(uname)["late_marks"] += 1
                if half_day:
                    ensure_summary(uname)["half_days"] += 1
                ensure_summary(uname)["total_ot_checkin_minutes"] += ot_in
                ensure_summary(uname)["total_ot_checkout_minutes"] += ot_out
            elif absent:
                ensure_summary(uname)["absent_days"] += 1

            sch = schedule_latest.get((uname, cur))
            ex = exception_latest.get((uname, cur))

            if present or (not is_weekend and u is not None):
                daily_rows.append(
                    {
                        "username": uname,
                        "date": cur.isoformat(),
                        "weekday": cur.strftime("%a"),
                        "first_punch": first.isoformat() if first else None,
                        "last_punch": last.isoformat() if last else None,
                        "hours_worked": hours_worked,
                        "hours_morning_window": hours_morning,
                        "hours_afternoon_window": hours_afternoon,
                        "first_half_short": first_half_short,
                        "second_half_short": second_half_short,
                        "late": late,
                        "half_day": half_day,
                        "ot_checkin_minutes": ot_in,
                        "ot_checkout_minutes": ot_out,
                        "on_approved_leave": on_leave,
                        "on_holiday": on_holiday,
                        "absent": absent,
                        "punch_count": len(day_punches),
                        "machine_schedule_code": sch.code if sch else None,
                        "machine_exception_late_min": ex.late_min if ex else None,
                        "machine_exception_early_min": ex.early_min if ex else None,
                        "machine_exception_absence_min": ex.absence_min if ex else None,
                    }
                )

            cur += timedelta(days=1)

    summaries = sorted(summary_by_user.values(), key=lambda x: x["username"])

    return {
        "month": month,
        "year": year,
        "attendance_settings": settings_to_dict(att_settings),
        "holidays": sorted([d.isoformat() for d in holiday_days_set]),
        "daily": daily_rows,
        "by_employee": summaries,
        "machine_statistics_imports": machine_statistics,
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role,
        },
    }
