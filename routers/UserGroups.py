# User Groups: create groups of users and assign to group (all members get assigned, group name stored)
from datetime import datetime
from utils.datetime_utils import ist_now
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from routers.auth import get_current_user, get_admin_user
from models.UserGroupModel import UserGroup, user_group_members
from models.UsersModel import User
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/user-groups", tags=["User Groups"])


class AddMembersBody(BaseModel):
    user_ids: List[int]


class UserGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    member_ids: Optional[List[int]] = None


class UserGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    member_ids: Optional[List[int]] = None


def _group_out(group: UserGroup, db: Session):
    members = db.query(User).filter(
        User.id.in_([m.id for m in group.members]),
        User.is_deleted == False
    ).all()
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "created_by_id": group.created_by_id,
        "created_at": group.created_at.isoformat() if group.created_at else None,
        "updated_at": group.updated_at.isoformat() if group.updated_at else None,
        "member_count": len(members),
        "members": [
            {"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name}
            for u in members
        ],
    }


@router.get("/list", response_model=List[dict])
def list_user_groups(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all non-deleted user groups with member count and members."""
    groups = db.query(UserGroup).filter(UserGroup.is_deleted == False).order_by(UserGroup.name).all()
    return [_group_out(g, db) for g in groups]


@router.post("/create", status_code=201)
def create_user_group(
    data: UserGroupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Create a user group (Admin only). Optionally set member_ids to add members."""
    existing = db.query(UserGroup).filter(UserGroup.is_deleted == False, UserGroup.name == data.name.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="A group with this name already exists")
    group = UserGroup(
        name=data.name.strip(),
        description=data.description.strip() if data.description else None,
        created_by_id=current_user.id,
    )
    db.add(group)
    db.flush()
    if data.member_ids:
        user_ids = [x for x in data.member_ids if x]
        users = db.query(User).filter(User.id.in_(user_ids), User.is_deleted == False).all()
        if len(users) != len(user_ids):
            found = {u.id for u in users}
            missing = [i for i in user_ids if i not in found]
            raise HTTPException(status_code=400, detail=f"User(s) not found: {missing}")
        group.members = users
    db.commit()
    db.refresh(group)
    return _group_out(group, db)


@router.get("/get/{group_id}")
def get_user_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.query(UserGroup).filter(UserGroup.id == group_id, UserGroup.is_deleted == False).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return _group_out(group, db)


@router.put("/update/{group_id}")
def update_user_group(
    group_id: int,
    data: UserGroupUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    group = db.query(UserGroup).filter(UserGroup.id == group_id, UserGroup.is_deleted == False).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if data.name is not None:
        other = db.query(UserGroup).filter(
            UserGroup.is_deleted == False,
            UserGroup.name == data.name.strip(),
            UserGroup.id != group_id
        ).first()
        if other:
            raise HTTPException(status_code=400, detail="A group with this name already exists")
        group.name = data.name.strip()
    if data.description is not None:
        group.description = data.description.strip() or None
    if data.member_ids is not None:
        user_ids = [x for x in data.member_ids if x]
        users = db.query(User).filter(User.id.in_(user_ids), User.is_deleted == False).all()
        if user_ids and len(users) != len(user_ids):
            found = {u.id for u in users}
            missing = [i for i in user_ids if i not in found]
            raise HTTPException(status_code=400, detail=f"User(s) not found: {missing}")
        group.members = users
    db.commit()
    db.refresh(group)
    return _group_out(group, db)


@router.delete("/delete/{group_id}")
def delete_user_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Soft-delete a user group."""
    group = db.query(UserGroup).filter(UserGroup.id == group_id, UserGroup.is_deleted == False).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    group.is_deleted = True
    group.deleted_at = ist_now()
    db.commit()
    return {"message": "Group deleted", "group_id": group_id}


@router.post("/add-members/{group_id}")
def add_members(
    group_id: int,
    body: AddMembersBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Add users to a group (by list of user IDs in body)."""
    group = db.query(UserGroup).filter(UserGroup.id == group_id, UserGroup.is_deleted == False).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    user_ids = [x for x in (body.user_ids or []) if x]
    users = db.query(User).filter(User.id.in_(user_ids), User.is_deleted == False).all()
    if user_ids and len(users) != len(user_ids):
        found = {u.id for u in users}
        missing = [i for i in user_ids if i not in found]
        raise HTTPException(status_code=400, detail=f"User(s) not found: {missing}")
    for u in users:
        if u not in group.members:
            group.members.append(u)
    db.commit()
    db.refresh(group)
    return _group_out(group, db)


@router.delete("/remove-member/{group_id}/{user_id}")
def remove_member(
    group_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Remove one user from a group."""
    group = db.query(UserGroup).filter(UserGroup.id == group_id, UserGroup.is_deleted == False).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user in group.members:
        group.members.remove(user)
    db.commit()
    db.refresh(group)
    return _group_out(group, db)
