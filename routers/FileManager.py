from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models.FileManagerModel import FileRecord
from models.UsersModel import User
from schemas.FileManagerSchema import (
    FileRecordCreate,
    FileRecordUpdate,
    FileRecordOut,
    FileManagerStats,
)
from routers.auth import get_current_user
import json


router = APIRouter(prefix="/file-manager", tags=["File Manager"])


def _encode_tags(tags: Optional[Union[List[str], str]]) -> Optional[str]:
    if tags is None:
        return None
    if isinstance(tags, str):
        parts = [t.strip() for t in tags.split(",") if t.strip()]
    else:
        parts = [str(t).strip() for t in tags if str(t).strip()]
    return json.dumps(parts) if parts else None


def _decode_tags(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(t) for t in data]
    except Exception:
        # Fallback: maybe comma-separated
        return [t.strip() for t in raw.split(",") if t.strip()]
    return []


def _record_to_out(rec: FileRecord) -> dict:
    return {
        "id": rec.id,
        "name": rec.name,
        "extension": rec.extension or "",
        "mime_type": rec.mime_type or "",
        "size_bytes": int(rec.size_bytes or 0),
        "last_modified_at": rec.last_modified_at.isoformat() if rec.last_modified_at else None,
        "category": rec.category or "",
        "tags": _decode_tags(rec.tags),
        "notes": rec.notes or "",
        "uploaded_at": rec.uploaded_at.isoformat() if rec.uploaded_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def _resolve_quota_bytes(user: User) -> int:
    """
    Match frontend logic:
    - Prefer bytes fields, then MB fields, then default 1024 MB.
    """
    # Bytes keys
    byte_keys = [
        "storage_quota_bytes",
        "storage_limit_bytes",
        "file_storage_bytes",
        "disk_space_bytes",
        "space_bytes",
    ]
    for key in byte_keys:
        if hasattr(user, key):
            val = getattr(user, key)
            if isinstance(val, (int, float)) and val > 0:
                return int(val)

    # MB keys
    mb_keys = [
        "storage_quota_mb",
        "storage_limit_mb",
        "file_storage_mb",
        "disk_space_mb",
        "space_mb",
    ]
    for key in mb_keys:
        if hasattr(user, key):
            val = getattr(user, key)
            if isinstance(val, (int, float)) and val > 0:
                return int(val * 1024 * 1024)

    # Fallback 1024 MB
    return 1024 * 1024 * 1024


@router.get("/list", response_model=List[dict])
def list_files(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: Optional[str] = Query(None, description="Search in name/notes/tags"),
    category: Optional[str] = Query(None),
):
    """List file records for current user with optional search and category filter."""
    q = db.query(FileRecord).filter(FileRecord.user_id == current_user.id)
    if category:
        q = q.filter(FileRecord.category == category)
    if search:
        like = f"%{search}%"
        q = q.filter(
            (FileRecord.name.ilike(like))
            | (FileRecord.notes.ilike(like))
            | (FileRecord.tags.ilike(like))
        )
    rows = q.order_by(FileRecord.uploaded_at.desc()).all()
    return [_record_to_out(r) for r in rows]


@router.post("/create", response_model=List[dict], status_code=201)
def create_files(
    payload: Union[FileRecordCreate, List[FileRecordCreate]],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create one or many file records with metadata.
    Frontend can send a single object or an array of objects.
    """
    if isinstance(payload, list):
        items = payload
    else:
        items = [payload]

    quota_bytes = _resolve_quota_bytes(current_user)
    # Current usage
    used_bytes = (
        db.query(func.coalesce(func.sum(FileRecord.size_bytes), 0))
        .filter(FileRecord.user_id == current_user.id)
        .scalar()
        or 0
    )

    new_size_total = sum(int(it.size_bytes or 0) for it in items)
    if used_bytes + new_size_total > quota_bytes:
        raise HTTPException(
            status_code=400,
            detail="Storage quota exceeded. Cannot upload these files.",
        )

    created: List[FileRecord] = []
    for data in items:
        rec = FileRecord(
            user_id=current_user.id,
            name=data.name.strip(),
            extension=(data.extension or "").strip() or None,
            mime_type=(data.mime_type or "").strip() or None,
            size_bytes=int(data.size_bytes or 0),
            category=(data.category or "").strip() or None,
            tags=_encode_tags(data.tags),
            notes=(data.notes or "").strip() or None,
            last_modified_at=data.last_modified_at,
        )
        db.add(rec)
        created.append(rec)

    db.commit()
    for rec in created:
        db.refresh(rec)
    return [_record_to_out(r) for r in created]


@router.put("/update/{file_id}", response_model=dict)
def update_file(
    file_id: int,
    data: FileRecordUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update category, tags, notes for a file record."""
    rec = (
        db.query(FileRecord)
        .filter(FileRecord.id == file_id, FileRecord.user_id == current_user.id)
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail="File record not found")

    payload = data.model_dump(exclude_unset=True)
    if "category" in payload:
        rec.category = (payload["category"] or "").strip() or None
    if "notes" in payload:
        rec.notes = (payload["notes"] or "").strip() or None
    if "tags" in payload:
        rec.tags = _encode_tags(payload["tags"])

    db.commit()
    db.refresh(rec)
    return _record_to_out(rec)


@router.delete("/delete/{file_id}", status_code=204)
def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rec = (
        db.query(FileRecord)
        .filter(FileRecord.id == file_id, FileRecord.user_id == current_user.id)
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail="File record not found")
    db.delete(rec)
    db.commit()
    return None


@router.delete("/clear-all", status_code=204)
def clear_all_files(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete all file records for current user."""
    db.query(FileRecord).filter(FileRecord.user_id == current_user.id).delete()
    db.commit()
    return None


@router.get("/stats", response_model=FileManagerStats)
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return storage usage stats for current user."""
    used_bytes = (
        db.query(func.coalesce(func.sum(FileRecord.size_bytes), 0))
        .filter(FileRecord.user_id == current_user.id)
        .scalar()
        or 0
    )
    quota_bytes = _resolve_quota_bytes(current_user)
    total_files = (
        db.query(func.count(FileRecord.id))
        .filter(FileRecord.user_id == current_user.id)
        .scalar()
        or 0
    )
    remaining = max(quota_bytes - int(used_bytes), 0)
    return FileManagerStats(
        used_bytes=int(used_bytes),
        quota_bytes=int(quota_bytes),
        remaining_bytes=int(remaining),
        total_files=int(total_files),
    )

