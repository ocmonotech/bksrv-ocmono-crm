from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from utils.activity import set_activity_description, describe_created, describe_updated, describe_deleted
from sqlalchemy.orm import Session
from typing import List, Optional
from models.LeadsModel import Lead, LeadAssignment
from models.UserGroupModel import UserGroup
from models.LeadTaskModel import LeadTask
from models.LeadNoteModel import LeadNote
from models.UsersModel import User
from schemas.LeadSchema import LeadCreate, LeadUpdate, LeadOut, LeadTaskOut, LeadNoteOut
from routers.auth import get_current_user, get_admin_user
from utils.notifications import create_notification
from database import get_db
from utils.welcome_email import send_welcome_email_to_lead
from datetime import datetime
from utils.datetime_utils import ist_now
from fastapi import Query
from sqlalchemy import or_, and_
from datetime import date
from pydantic import BaseModel
from typing import List

router = APIRouter(prefix="/leads", tags=["Leads"])


def _lead_row_to_leadout_data(lead: Lead, db: Session) -> dict:
    """Build a dict that satisfies LeadOut (assigned_users as user dicts, not ORM)."""
    assignments = (
        db.query(User.id, User.username, User.first_name, User.last_name)
        .join(LeadAssignment, LeadAssignment.user_id == User.id)
        .filter(LeadAssignment.lead_id == lead.id)
        .all()
    )
    assigned_users = [
        {"id": uid, "username": username, "first_name": first_name, "last_name": last_name}
        for uid, username, first_name, last_name in assignments
    ]
    data = {c.key: getattr(lead, c.key) for c in Lead.__table__.columns}
    data.update(
        {
            "assigned_to_id": assigned_users[0]["id"] if assigned_users else None,
            "assigned_to_username": assigned_users[0]["username"] if assigned_users else None,
            "assigned_to_ids": [u["id"] for u in assigned_users],
            "assigned_users": assigned_users,
            "tasks": [],
            "notes": [],
        }
    )
    return data


class PaginatedLeadOut(BaseModel):
    items: List[LeadOut]
    total: int
    page: int
    limit: int
    total_converted: int = 0
    total_new: int = 0
    total_high_priority: int = 0

# Create a new lead
@router.post("/create-lead", response_model=LeadOut)
def create_lead(
    request: Request,
    lead: LeadCreate, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db), 
    current_user=Depends(get_current_user)
):
    lead_data = lead.dict()
    # Extract assignment fields (not direct fields on Lead model)
    assigned_to_id = lead_data.pop('assigned_to_id', None)
    assigned_to_ids = lead_data.pop('assigned_to_ids', None) or []
    assigned_to_group_id = lead_data.pop('assigned_to_group_id', None)
    final_assignee_ids: List[int] = []
    if assigned_to_group_id:
        group = db.query(UserGroup).filter(UserGroup.id == assigned_to_group_id, UserGroup.is_deleted == False).first()
        if not group:
            raise HTTPException(status_code=400, detail="User group not found")
        final_assignee_ids = [u.id for u in group.members if not getattr(u, "is_deleted", False)]
    elif assigned_to_ids:
        final_assignee_ids = [int(x) for x in assigned_to_ids if x]
    elif assigned_to_id:
        final_assignee_ids = [int(assigned_to_id)]
    final_assignee_ids = list(dict.fromkeys(final_assignee_ids))
    
    lead_data['created_by'] = current_user.username
    lead_data['created_at'] = ist_now()
    lead_data['date_created'] = ist_now()
    db_lead = Lead(**lead_data)
    db.add(db_lead)
    db.commit()
    db.refresh(db_lead)
    
    # Create LeadAssignment rows for all assignees
    if final_assignee_ids:
        users = db.query(User).filter(User.id.in_(final_assignee_ids), User.is_deleted == False).all()
        if len(users) != len(final_assignee_ids):
            found = {u.id for u in users}
            missing = [i for i in final_assignee_ids if i not in found]
            raise HTTPException(status_code=400, detail=f"User(s) not found: {missing}")
        for uid in final_assignee_ids:
            db.add(LeadAssignment(lead_id=db_lead.id, user_id=uid))
        db.commit()
        for uid in final_assignee_ids:
            create_notification(
                db,
                uid,
                f"New lead assigned: {db_lead.name or db_lead.email or f'Lead #{db_lead.id}'}",
                notif_type="lead",
                target_url=f"/leads/{db_lead.id}",
                entity_id=db_lead.id,
            )
    
    # Send welcome email in background
    background_tasks.add_task(send_welcome_email_to_lead, db_lead.id)
    set_activity_description(request, describe_created("lead", f"#{db_lead.id}", db_lead.name or db_lead.email))
    return _lead_row_to_leadout_data(db_lead, db)


# Get all leads (includes assigned user info, tasks from lead_tasks, notes from lead_notes)
@router.get("/leads-list", response_model=PaginatedLeadOut)
def get_all_leads(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    assigned_to: Optional[int] = Query(None),
    priority: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    all_status: Optional[str] = Query(None, description="Filter by status(es). Comma-separated or repeated: e.g. all_status=New&all_status=Contacted or all_status=New,Contacted"),
    all_campaign_ids: Optional[str] = Query(None, description="Filter by campaign ID(s). Comma-separated or repeated: e.g. all_campaign_ids=1&all_campaign_ids=2 or all_campaign_ids=1,2"),
    all_users: Optional[str] = Query(None, description="Filter by assigned user ID(s). Comma-separated or repeated: e.g. all_users=1&all_users=2 or all_users=1,2"),
    total_converted: Optional[int] = Query(None),
    total_new: Optional[int] = Query(None),
    total_high_priority: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    offset = (page - 1) * limit

    # Normalize list params (FastAPI may pass single value or frontend may send comma-separated)
    def _ensure_str_list(val):
        if val is None:
            return None
        if isinstance(val, str):
            return [v.strip() for v in val.split(",") if v.strip()]
        if isinstance(val, list):
            return [str(v) for v in val]
        return [str(val)]

    def _ensure_int_list(val):
        if val is None:
            return None
        if isinstance(val, (str, bytes)):
            return [int(x.strip()) for x in str(val).split(",") if x.strip().isdigit()]
        if isinstance(val, int):
            return [val]
        if isinstance(val, list):
            return [int(x) for x in val if x is not None]
        return None

    status_list = _ensure_str_list(all_status) if all_status else None
    campaign_list = _ensure_int_list(all_campaign_ids) if all_campaign_ids else None
    users_list = _ensure_int_list(all_users) if all_users else None

    base_query = db.query(Lead).filter(Lead.is_deleted == False)

    # Search
    if search:
        base_query = base_query.filter(
            or_(
                Lead.name.ilike(f"%{search}%"),
                Lead.email.ilike(f"%{search}%"),
                Lead.phone.ilike(f"%{search}%"),
                Lead.source.ilike(f"%{search}%"),
                Lead.city.ilike(f"%{search}%"),
            )
        )

    # Filters
    if assigned_to:
        base_query = base_query.filter(
            Lead.id.in_(
                db.query(LeadAssignment.lead_id).filter(LeadAssignment.user_id == assigned_to)
            )
        )

    if priority:
        base_query = base_query.filter(Lead.priority == priority)

    if status_list:
        base_query = base_query.filter(Lead.status.in_(status_list))

    if campaign_list:
        base_query = base_query.filter(Lead.campaign_id.in_(campaign_list))

    if users_list:
        base_query = base_query.filter(
            Lead.id.in_(
                db.query(LeadAssignment.lead_id).filter(LeadAssignment.user_id.in_(users_list))
            )
        )


    # Total count (before pagination)
    count_query = base_query

    converted = count_query.filter(Lead.status == "Converted").count()
    new_leads = count_query.filter(Lead.status == "New").count()
    high_priority_leads = count_query.filter(Lead.priority == "High").count()
    total = count_query.count()

    # Pagination
    rows = (
        base_query
        .order_by(Lead.date_created.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    lead_ids = [lead.id for lead in rows]

    # Batch load tasks & notes
    tasks_by_lead = {}
    notes_by_lead = {}

    if lead_ids:
        for t in db.query(LeadTask).filter(LeadTask.lead_id.in_(lead_ids), LeadTask.is_deleted == False):
            tasks_by_lead.setdefault(t.lead_id, []).append(LeadTaskOut.model_validate(t))

        for n in db.query(LeadNote).filter(LeadNote.lead_id.in_(lead_ids), LeadNote.is_deleted == False):
            notes_by_lead.setdefault(n.lead_id, []).append(LeadNoteOut.model_validate(n))

    items = []
    assignees_map = {}
    if lead_ids:
        assignment_rows = (
            db.query(LeadAssignment.lead_id, User.id, User.username, User.first_name, User.last_name)
            .join(User, LeadAssignment.user_id == User.id)
            .filter(LeadAssignment.lead_id.in_(lead_ids))
            .all()
        )
        for lead_id, user_id, username, first_name, last_name in assignment_rows:
            assignees_map.setdefault(lead_id, []).append(
                {
                    "id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                }
            )

    for lead in rows:
        assigned_users = assignees_map.get(lead.id, [])
        data = {c.key: getattr(lead, c.key) for c in Lead.__table__.columns}
        data.update({
            "assigned_to_id": assigned_users[0]["id"] if assigned_users else None,  # backward compatibility
            "assigned_to_username": assigned_users[0]["username"] if assigned_users else None,  # backward compatibility
            "assigned_to_ids": [u["id"] for u in assigned_users],
            "assigned_users": assigned_users,
            "tasks": tasks_by_lead.get(lead.id, []),
            "notes": notes_by_lead.get(lead.id, []),
        })
        items.append(LeadOut(**data))

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_converted": converted,
        "total_new": new_leads,
        "total_high_priority": high_priority_leads,
    }

# Get a lead by ID
@router.get("/get-lead/{lead_id}", response_model=LeadOut)
def get_lead_by_id(lead_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.is_deleted == False).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _lead_row_to_leadout_data(lead, db)

# Update a lead
@router.put("/update-lead/{lead_id}", response_model=LeadOut)
def update_lead(request: Request, lead_id: int, lead: LeadUpdate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    db_lead = db.query(Lead).filter(Lead.id == lead_id, Lead.is_deleted == False).first()
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    old_assigned_ids = {r.user_id for r in db.query(LeadAssignment).filter(LeadAssignment.lead_id == lead_id).all()}
    
    # Only get fields that are explicitly set in the request
    update_data = lead.model_dump(exclude_unset=True)

    if "row_color" in update_data:
        rc = update_data["row_color"]
        update_data["row_color"] = None if rc is None or (isinstance(rc, str) and not rc.strip()) else rc.strip()

    # Handle assignment fields separately (not direct fields on Lead model)
    assigned_to_id_provided = 'assigned_to_id' in update_data
    assigned_to_id = update_data.pop('assigned_to_id', None) if assigned_to_id_provided else None
    assigned_to_ids_provided = 'assigned_to_ids' in update_data
    assigned_to_ids = update_data.pop('assigned_to_ids', None) if assigned_to_ids_provided else None
    assigned_to_group_id_provided = 'assigned_to_group_id' in update_data
    assigned_to_group_id = update_data.pop('assigned_to_group_id', None) if assigned_to_group_id_provided else None
    
    # Update only the fields that are present in the request
    # Fields not included in the request will remain unchanged
    for key, value in update_data.items():
        # Only update if the field exists on the model
        if hasattr(db_lead, key):
            setattr(db_lead, key, value)
    
    # Handle assignment updates only if any assignment field is explicitly provided
    if assigned_to_id_provided or assigned_to_ids_provided or assigned_to_group_id_provided:
        new_assignee_ids: List[int] = []
        if assigned_to_group_id_provided and assigned_to_group_id:
            group = db.query(UserGroup).filter(UserGroup.id == assigned_to_group_id, UserGroup.is_deleted == False).first()
            if not group:
                raise HTTPException(status_code=400, detail="User group not found")
            new_assignee_ids = [u.id for u in group.members if not getattr(u, "is_deleted", False)]
        elif assigned_to_ids_provided:
            new_assignee_ids = [int(x) for x in (assigned_to_ids or []) if x]
        elif assigned_to_id_provided and assigned_to_id:
            new_assignee_ids = [int(assigned_to_id)]

        new_assignee_ids = list(dict.fromkeys(new_assignee_ids))
        users = db.query(User).filter(User.id.in_(new_assignee_ids), User.is_deleted == False).all() if new_assignee_ids else []
        if len(users) != len(new_assignee_ids):
            found = {u.id for u in users}
            missing = [i for i in new_assignee_ids if i not in found]
            raise HTTPException(status_code=400, detail=f"User(s) not found: {missing}")

        db.query(LeadAssignment).filter(LeadAssignment.lead_id == lead_id).delete()
        for uid in new_assignee_ids:
            db.add(LeadAssignment(lead_id=lead_id, user_id=uid))
    
    # Always update the date_updated timestamp when any field is updated
    db_lead.date_updated = ist_now()
    db.commit()
    db.refresh(db_lead)
    new_assigned_ids = {r.user_id for r in db.query(LeadAssignment).filter(LeadAssignment.lead_id == lead_id).all()}
    newly_assigned = new_assigned_ids - old_assigned_ids
    for uid in newly_assigned:
        create_notification(
            db,
            uid,
            f"You were assigned a lead: {db_lead.name or db_lead.email or f'Lead #{db_lead.id}'}",
            notif_type="lead",
            target_url=f"/leads/{db_lead.id}",
            entity_id=db_lead.id,
        )
    changed = ", ".join(k for k in update_data.keys() if k != "assigned_to_id") or "details"
    set_activity_description(request, describe_updated("lead", f"#{lead_id}", changed))
    return _lead_row_to_leadout_data(db_lead, db)

# Delete a lead (soft delete)
@router.delete("/delete-lead/{lead_id}")
def delete_lead(request: Request, lead_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    db_lead = db.query(Lead).filter(Lead.id == lead_id, Lead.is_deleted == False).first()
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    name = db_lead.name or db_lead.email
    db_lead.is_deleted = True
    db_lead.deleted_at = ist_now()
    db.commit()
    set_activity_description(request, describe_deleted("lead", f"#{lead_id}", name))
    return {"detail": "Lead deleted successfully"}


# Hard delete a lead (Admin only)
@router.delete("/delete-lead/{lead_id}/hard-delete")
def hard_delete_lead(
    request: Request,
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    db_lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    name = db_lead.name or db_lead.email
    db.delete(db_lead)
    db.commit()
    set_activity_description(request, describe_deleted("lead (hard)", f"#{lead_id}", name))
    return {"detail": "Lead permanently deleted"}
