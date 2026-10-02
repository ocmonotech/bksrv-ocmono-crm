from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import String, cast, func
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models.AppSheetModel import AppSheetConnection, AppSheetRow, AppSheetSyncLog
from models.SettingsModel import Settings
from routers.auth import get_current_user
from schemas.AppSheetSchema import (
    AppSheetConnectionCreate,
    AppSheetConnectionOut,
    AppSheetConnectionUpdate,
    AppSheetCredentialsIn,
    AppSheetCredentialsOut,
    AppSheetRowCreate,
    AppSheetRowOut,
    AppSheetRowUpdate,
    AppSheetRowsPage,
    AppSheetStats,
    AppSheetSyncLogOut,
)
from utils.datetime_utils import IST, ist_now
from utils.google_sheets_client import (
    SETTINGS_KEY,
    append_sheet_row,
    extract_gid_from_url,
    extract_sheet_id_from_url,
    fetch_sheet_records,
    is_write_ready,
    list_worksheet_titles,
    parse_service_account_json,
    row_checksum,
    service_account_email,
    update_sheet_row,
)

router = APIRouter(prefix="/app-sheets", tags=["Sheets"])


def _as_ist(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def _sync_frequency_delta(sync_frequency: Optional[str]) -> timedelta:
    mapping = {
        "Every 5 minutes": timedelta(minutes=5),
        "Every 15 minutes": timedelta(minutes=15),
        "Every 30 minutes": timedelta(minutes=30),
        "Hourly": timedelta(hours=1),
        "Daily": timedelta(days=1),
    }
    return mapping.get((sync_frequency or "").strip(), timedelta(minutes=15))


def _is_active(connection: AppSheetConnection) -> bool:
    return (connection.status or "").strip().lower() == "active"


def _connection_should_sync_now(connection: AppSheetConnection, now) -> bool:
    if not _is_active(connection):
        return False
    ns = _as_ist(connection.next_sync)
    if ns is None or ns <= now:
        return True
    interval = _sync_frequency_delta(connection.sync_frequency)
    ls = _as_ist(connection.last_sync)
    if ls is None:
        return True
    return (now - ls) >= interval


def _dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=True)
    return model.dict(exclude_unset=True)


def _row_to_out(row: AppSheetRow, write_error: Optional[str] = None) -> dict:
    return {
        "id": row.id,
        "connection_id": row.connection_id,
        "row_number": row.row_number,
        "data": row.data or {},
        "dirty": bool(row.dirty),
        "updated_from": row.updated_from,
        "updated_at": row.updated_at,
        "write_error": write_error,
    }


def sync_app_sheet(connection_id: int) -> None:
    db = SessionLocal()
    try:
        connection = db.query(AppSheetConnection).filter(AppSheetConnection.id == connection_id).first()
        if not connection:
            return
        if not _is_active(connection):
            return

        headers, records, via_api = fetch_sheet_records(
            connection.sheet_id,
            connection.sheet_name or "Sheet1",
            connection.gid,
            db=db,
        )
        connection.headers = headers

        existing_rows = (
            db.query(AppSheetRow)
            .filter(AppSheetRow.connection_id == connection.id)
            .all()
        )
        by_number = {row.row_number: row for row in existing_rows}
        seen_numbers = set()
        synced = 0

        for index, record in enumerate(records):
            row_number = index + 2  # header is row 1
            seen_numbers.add(row_number)
            checksum = row_checksum(record)
            current = by_number.get(row_number)
            if current and current.dirty:
                continue
            if current:
                if current.checksum != checksum:
                    current.data = record
                    current.checksum = checksum
                    current.updated_from = "google"
                    current.dirty = False
                    current.updated_at = ist_now()
                synced += 1
            else:
                db.add(AppSheetRow(
                    connection_id=connection.id,
                    row_number=row_number,
                    data=record,
                    checksum=checksum,
                    dirty=False,
                    updated_from="google",
                    created_at=ist_now(),
                    updated_at=ist_now(),
                ))
                synced += 1

        for row in existing_rows:
            if row.row_number not in seen_numbers and not row.dirty:
                db.delete(row)

        connection.row_count = len(records)
        connection.last_sync = ist_now()
        connection.next_sync = ist_now() + _sync_frequency_delta(connection.sync_frequency)
        db.add(AppSheetSyncLog(
            connection_id=connection.id,
            connection_name=connection.name,
            status="Success",
            rows_synced=synced,
            message=f"Synced {len(records)} row(s) from Google Sheets{' via API' if via_api else ' via public CSV'}.",
            created_at=ist_now(),
        ))
        db.commit()
    except Exception as exc:
        db.rollback()
        db_err = SessionLocal()
        try:
            connection = db_err.query(AppSheetConnection).filter(AppSheetConnection.id == connection_id).first()
            if connection:
                connection.errors = (connection.errors or 0) + 1
                connection.last_sync = ist_now()
                db_err.add(AppSheetSyncLog(
                    connection_id=connection.id,
                    connection_name=connection.name,
                    status="Error",
                    rows_synced=0,
                    message=f"Sync failed: {str(exc)[:500]}",
                    error_details=str(exc)[:2000],
                    created_at=ist_now(),
                ))
                db_err.commit()
        finally:
            db_err.close()
        print(f"[AppSheets] sync error connection_id={connection_id}: {exc}")
    finally:
        db.close()


def run_due_app_sheet_syncs() -> None:
    db = SessionLocal()
    try:
        now = ist_now()
        candidates = (
            db.query(AppSheetConnection)
            .filter(func.lower(func.trim(AppSheetConnection.status)) == "active")
            .all()
        )
        for conn in candidates:
            if not _connection_should_sync_now(conn, now):
                continue
            try:
                sync_app_sheet(conn.id)
            except Exception as exc:
                print(f"[AppSheets] scheduled sync error connection_id={conn.id}: {exc}")
    finally:
        db.close()


@router.get("/credentials", response_model=AppSheetCredentialsOut)
def get_credentials(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    email = service_account_email(db)
    ready = is_write_ready(db)
    return {
        "configured": bool(email),
        "write_ready": ready,
        "client_email": email,
        "message": (
            f"Share each Google Sheet with {email} as Editor so the CRM can sync and update it."
            if email
            else "Paste a Google Cloud service account JSON key to enable private-sheet sync and write-back."
        ),
    }


@router.post("/credentials", response_model=AppSheetCredentialsOut)
def save_credentials(
    data: AppSheetCredentialsIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    info = parse_service_account_json(data.service_account_json)
    setting = db.query(Settings).filter(Settings.key == SETTINGS_KEY).first()
    if setting:
        setting.value = data.service_account_json.strip()
        setting.description = "Google Sheets service account JSON for bidirectional sync"
    else:
        setting = Settings(
            key=SETTINGS_KEY,
            value=data.service_account_json.strip(),
            description="Google Sheets service account JSON for bidirectional sync",
        )
        db.add(setting)
    db.commit()
    email = info.get("client_email")
    return {
        "configured": True,
        "write_ready": True,
        "client_email": email,
        "message": f"Saved. Share your Google Sheets with {email} as Editor.",
    }


@router.delete("/credentials", response_model=dict)
def delete_credentials(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    setting = db.query(Settings).filter(Settings.key == SETTINGS_KEY).first()
    if setting:
        db.delete(setting)
        db.commit()
    return {"message": "Google Sheets credentials removed"}


@router.get("/stats", response_model=AppSheetStats)
def get_stats(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    active = db.query(AppSheetConnection).filter(AppSheetConnection.status == "Active").count()
    total_rows = db.query(func.count(AppSheetRow.id)).scalar() or 0
    today_start = ist_now().replace(hour=0, minute=0, second=0, microsecond=0)
    todays_syncs = db.query(AppSheetSyncLog).filter(AppSheetSyncLog.created_at >= today_start).count()
    errors = db.query(func.sum(AppSheetConnection.errors)).scalar() or 0
    email = service_account_email(db)
    return {
        "active_connections": active,
        "total_rows": int(total_rows),
        "todays_syncs": todays_syncs,
        "errors": int(errors),
        "write_ready": is_write_ready(db),
        "service_account_email": email,
    }


@router.post("/connect", response_model=AppSheetConnectionOut)
def connect_sheet(
    data: AppSheetConnectionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    sheet_id = extract_sheet_id_from_url(data.sheet_url)
    if not sheet_id:
        raise HTTPException(status_code=400, detail="Invalid Google Sheet URL")

    existing = db.query(AppSheetConnection).filter(AppSheetConnection.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="A connection with this name already exists")

    connection = AppSheetConnection(
        name=data.name.strip(),
        sheet_url=data.sheet_url.strip(),
        sheet_id=sheet_id,
        sheet_name=(data.sheet_name or "Sheet1").strip() or "Sheet1",
        gid=extract_gid_from_url(data.sheet_url),
        sync_frequency=data.sync_frequency or "Every 15 minutes",
        status=data.status or "Active",
        next_sync=ist_now(),
        write_enabled=True,
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    background_tasks.add_task(sync_app_sheet, connection.id)
    return connection


@router.get("/connections", response_model=List[AppSheetConnectionOut])
def list_connections(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = db.query(AppSheetConnection)
    if search:
        query = query.filter(AppSheetConnection.name.ilike(f"%{search}%"))
    if status:
        query = query.filter(AppSheetConnection.status == status)
    return query.order_by(AppSheetConnection.created_at.desc()).all()


@router.get("/connections/{connection_id}", response_model=AppSheetConnectionOut)
def get_connection(connection_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    connection = db.query(AppSheetConnection).filter(AppSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


@router.put("/connections/{connection_id}", response_model=AppSheetConnectionOut)
def update_connection(
    connection_id: int,
    data: AppSheetConnectionUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    connection = db.query(AppSheetConnection).filter(AppSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    payload = _dump(data)
    if payload.get("sheet_url"):
        sheet_id = extract_sheet_id_from_url(payload["sheet_url"])
        if not sheet_id:
            raise HTTPException(status_code=400, detail="Invalid Google Sheet URL")
        payload["sheet_id"] = sheet_id
        payload["gid"] = extract_gid_from_url(payload["sheet_url"])
    for key, value in payload.items():
        setattr(connection, key, value)
    connection.updated_at = ist_now()
    db.commit()
    db.refresh(connection)
    return connection


@router.delete("/connections/{connection_id}")
def delete_connection(connection_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    connection = db.query(AppSheetConnection).filter(AppSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    db.query(AppSheetSyncLog).filter(AppSheetSyncLog.connection_id == connection_id).delete()
    db.delete(connection)
    db.commit()
    return {"message": "Connection deleted"}


@router.get("/connections/{connection_id}/worksheets")
def get_worksheets(connection_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    connection = db.query(AppSheetConnection).filter(AppSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        titles = list_worksheet_titles(connection.sheet_id, db=db)
        return {"worksheets": titles, "current": connection.sheet_name}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/connections/{connection_id}/sync", response_model=dict)
def trigger_sync(
    connection_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    connection = db.query(AppSheetConnection).filter(AppSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    background_tasks.add_task(sync_app_sheet, connection_id)
    return {"message": "Sync started", "connection_id": connection_id}


@router.post("/sync-all", response_model=dict)
def sync_all(background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    connections = (
        db.query(AppSheetConnection)
        .filter(func.lower(func.trim(AppSheetConnection.status)) == "active")
        .all()
    )
    for connection in connections:
        background_tasks.add_task(sync_app_sheet, connection.id)
    return {"message": f"Sync started for {len(connections)} active connection(s)", "count": len(connections)}


@router.get("/connections/{connection_id}/rows", response_model=AppSheetRowsPage)
def list_rows(
    connection_id: int,
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    connection = db.query(AppSheetConnection).filter(AppSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    query = db.query(AppSheetRow).filter(AppSheetRow.connection_id == connection_id)
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(cast(AppSheetRow.data, String).ilike(like))
    total = query.count()
    rows = query.order_by(AppSheetRow.row_number.asc()).offset(skip).limit(limit).all()
    return {
        "connection": connection,
        "headers": connection.headers or [],
        "total": total,
        "skip": skip,
        "limit": limit,
        "rows": [_row_to_out(row) for row in rows],
        "write_ready": is_write_ready(db),
    }


@router.post("/connections/{connection_id}/rows", response_model=AppSheetRowOut)
def add_row(
    connection_id: int,
    data: AppSheetRowCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    connection = db.query(AppSheetConnection).filter(AppSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    headers = connection.headers or list((data.values or {}).keys())
    if not headers:
        raise HTTPException(status_code=400, detail="Sync the sheet first so columns are known")
    values = {h: str((data.values or {}).get(h, "") or "") for h in headers}
    try:
        row_number = append_sheet_row(
            connection.sheet_id,
            connection.sheet_name or "Sheet1",
            headers,
            values,
            db=db,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not row_number:
        last = (
            db.query(func.max(AppSheetRow.row_number))
            .filter(AppSheetRow.connection_id == connection_id)
            .scalar()
        )
        row_number = int(last or 1) + 1
    existing = (
        db.query(AppSheetRow)
        .filter(AppSheetRow.connection_id == connection.id, AppSheetRow.row_number == row_number)
        .first()
    )
    if existing:
        existing.data = values
        existing.checksum = row_checksum(values)
        existing.dirty = False
        existing.updated_from = "app"
        existing.updated_at = ist_now()
        db.commit()
        db.refresh(existing)
        return _row_to_out(existing)
    row = AppSheetRow(
        connection_id=connection.id,
        row_number=row_number,
        data=values,
        checksum=row_checksum(values),
        dirty=False,
        updated_from="app",
        created_at=ist_now(),
        updated_at=ist_now(),
    )
    db.add(row)
    connection.row_count = (connection.row_count or 0) + 1
    db.commit()
    db.refresh(row)
    return _row_to_out(row)


@router.patch("/connections/{connection_id}/rows/{row_id}", response_model=AppSheetRowOut)
def update_row(
    connection_id: int,
    row_id: int,
    data: AppSheetRowUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    connection = db.query(AppSheetConnection).filter(AppSheetConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    row = (
        db.query(AppSheetRow)
        .filter(AppSheetRow.id == row_id, AppSheetRow.connection_id == connection_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Row not found")

    headers = connection.headers or list((row.data or {}).keys())
    merged = dict(row.data or {})
    for key, value in (data.values or {}).items():
        merged[key] = "" if value is None else str(value)
    merged = {h: merged.get(h, "") for h in headers} if headers else merged

    write_error = None
    try:
        update_sheet_row(
            connection.sheet_id,
            connection.sheet_name or "Sheet1",
            row.row_number,
            headers,
            merged,
            db=db,
        )
        row.dirty = False
        row.updated_from = "app"
    except Exception as exc:
        row.dirty = True
        row.updated_from = "app"
        write_error = str(exc)

    row.data = merged
    row.checksum = row_checksum(merged)
    row.updated_at = ist_now()
    db.commit()
    db.refresh(row)
    return _row_to_out(row, write_error)


@router.get("/sync-logs", response_model=List[AppSheetSyncLogOut])
def get_sync_logs(
    connection_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = db.query(AppSheetSyncLog)
    if connection_id:
        query = query.filter(AppSheetSyncLog.connection_id == connection_id)
    return query.order_by(AppSheetSyncLog.created_at.desc()).offset(skip).limit(limit).all()
