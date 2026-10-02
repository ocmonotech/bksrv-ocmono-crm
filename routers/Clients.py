# clients.py – Client CRUD and dashboard (add, edit, update, delete, list, status)
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from utils.activity import set_activity_description, describe_created, describe_updated, describe_deleted
from sqlalchemy import or_, func
from database import get_db
from routers.auth import get_current_user, get_admin_user
from models.ClientModel import Client
from models.ProjectModel import Project
from models.AssignmentModel import Assignment
from models.ProjectTimerModel import ProjectTimer
from models.UsersModel import User
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from utils.datetime_utils import ist_now

router = APIRouter(prefix="/clients", tags=["Clients"])


class ClientCreate(BaseModel):
    client_name: str
    contact_person: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    status: Optional[str] = "Active"
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    notes: Optional[str] = None


class ClientUpdate(BaseModel):
    client_name: str
    contact_person: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    status: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    notes: Optional[str] = None


# ----- List all clients (with project/assignment counts, search, status filter) -----
@router.get("/all-clients")
def list_clients(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    query = db.query(Client).filter(Client.is_deleted == False).order_by(Client.id.desc())
    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                Client.client_name.ilike(term),
                Client.contact_person.ilike(term),
                Client.email.ilike(term),
                Client.phone.ilike(term),
                Client.company.ilike(term),
            )
        )
    if status_filter:
        query = query.filter(Client.status == status_filter)

    clients = query.all()
    client_ids = [c.id for c in clients]

    project_counts = {}
    assignment_counts = {}
    last_work_by_client = {}
    if client_ids:
        proj_counts = db.query(Project.client_id, func.count(Project.id)).filter(
            Project.client_id.in_(client_ids), Project.is_deleted == False
        ).group_by(Project.client_id).all()
        project_counts = {cid: cnt for cid, cnt in proj_counts}

        assign_counts = db.query(Assignment.client_id, func.count(Assignment.id)).filter(
            Assignment.client_id.in_(client_ids), Assignment.is_deleted == False
        ).group_by(Assignment.client_id).all()
        assignment_counts = {cid: cnt for cid, cnt in assign_counts}

        last_updates = db.query(
            Assignment.client_id,
            func.max(Assignment.updated_at).label("last_at")
        ).filter(Assignment.client_id.in_(client_ids), Assignment.is_deleted == False, Assignment.updated_at.isnot(None)).group_by(Assignment.client_id).all()
        last_work_by_client = {cid: (last_at.isoformat() if last_at else None) for cid, last_at in last_updates}

    return {
        "clients": [
            {
                "id": c.id,
                "client_name": c.client_name,
                "contact_person": getattr(c, "contact_person", None),
                "email": getattr(c, "email", None),
                "phone": getattr(c, "phone", None),
                "company": getattr(c, "company", None),
                "status": getattr(c, "status", None) or "Active",
                "address": getattr(c, "address", None),
                "city": getattr(c, "city", None),
                "country": getattr(c, "country", None),
                "notes": getattr(c, "notes", None),
                "project_count": project_counts.get(c.id, 0),
                "assignment_count": assignment_counts.get(c.id, 0),
                "task_count": assignment_counts.get(c.id, 0),
                "last_work": last_work_by_client.get(c.id),
            }
            for c in clients
        ],
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        }
    }


# ----- Add client -----
@router.post("/add-client")
def add_client(
    request: Request,
    client_data: ClientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    existing = db.query(Client).filter(Client.client_name == client_data.client_name, Client.is_deleted == False).first()
    if existing:
        raise HTTPException(status_code=400, detail="Client already exists")

    new_client = Client(
        client_name=client_data.client_name,
        contact_person=client_data.contact_person,
        email=client_data.email,
        phone=client_data.phone,
        company=client_data.company,
        status=client_data.status or "Active",
        address=client_data.address,
        city=client_data.city,
        country=client_data.country,
        notes=client_data.notes,
    )
    db.add(new_client)
    db.commit()
    db.refresh(new_client)
    set_activity_description(request, describe_created("client", new_client.client_name))

    return {
        "message": "Client added successfully",
        "client": {
            "id": new_client.id,
            "client_name": new_client.client_name,
            "contact_person": new_client.contact_person,
            "email": new_client.email,
            "phone": new_client.phone,
            "company": new_client.company,
            "status": new_client.status,
            "address": new_client.address,
            "city": new_client.city,
            "country": new_client.country,
            "notes": new_client.notes,
        }
    }


# ----- Get client for editing -----
@router.get("/edit-client/{client_id}")
def get_edit_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    client = db.query(Client).filter(Client.id == client_id, Client.is_deleted == False).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    return {
        "client": {
            "id": client.id,
            "client_name": client.client_name,
            "contact_person": getattr(client, "contact_person", None),
            "email": getattr(client, "email", None),
            "phone": getattr(client, "phone", None),
            "company": getattr(client, "company", None),
            "status": getattr(client, "status", None) or "Active",
            "address": getattr(client, "address", None),
            "city": getattr(client, "city", None),
            "country": getattr(client, "country", None),
            "notes": getattr(client, "notes", None),
        },
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        }
    }


# ----- Update client -----
@router.put("/edit-client/{client_id}")
def edit_client(
    request: Request,
    client_id: int,
    client_data: ClientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    client = db.query(Client).filter(Client.id == client_id, Client.is_deleted == False).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    existing = db.query(Client).filter(Client.client_name == client_data.client_name, Client.id != client_id, Client.is_deleted == False).first()
    if existing:
        raise HTTPException(status_code=400, detail="Client name already exists")

    client.client_name = client_data.client_name
    client.contact_person = client_data.contact_person
    client.email = client_data.email
    client.phone = client_data.phone
    client.company = client_data.company
    if client_data.status is not None:
        client.status = client_data.status
    client.address = client_data.address
    client.city = client_data.city
    client.country = client_data.country
    client.notes = client_data.notes

    related_projects = db.query(Project).filter(Project.client_id == client_id).all()
    for project in related_projects:
        project.project_client = client_data.client_name

    db.commit()
    db.refresh(client)
    set_activity_description(request, describe_updated("client", client.client_name, "name, contact, email, status, etc."))

    return {
        "message": "Client updated successfully",
        "client": {
            "id": client.id,
            "client_name": client.client_name,
            "contact_person": client.contact_person,
            "email": client.email,
            "phone": client.phone,
            "company": client.company,
            "status": client.status,
            "address": client.address,
            "city": client.city,
            "country": client.country,
            "notes": client.notes,
        }
    }


# ----- Delete client (soft delete) -----
@router.delete("/delete-client/{client_id}")
def delete_client(
    request: Request,
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access forbidden")

    client = db.query(Client).filter(Client.id == client_id, Client.is_deleted == False).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    name = client.client_name
    client.is_deleted = True
    client.deleted_at = ist_now()
    db.commit()
    set_activity_description(request, describe_deleted("client", name))
    return {"message": "Client deleted successfully", "client_id": client_id}


# ----- Hard delete client (Admin only) -----
@router.delete("/delete-client/{client_id}/hard-delete")
def hard_delete_client(
    request: Request,
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    name = client.client_name
    db.delete(client)
    db.commit()
    set_activity_description(request, describe_deleted("client (hard)", name))
    return {"message": "Client permanently deleted", "client_id": client_id}


# ----- Client status dashboard (projects summary for a client) -----
@router.get("/{client_id}/status")
def client_status_dashboard(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access denied")

    client = db.query(Client).filter(Client.id == client_id, Client.is_deleted == False).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    projects = db.query(Project).filter(Project.client_id == client_id, Project.is_deleted == False).all()
    total_projects = len(projects)
    completed = in_progress = not_started = 0
    all_project_ids = [p.id for p in projects]

    for p in projects:
        if p.project_status == "Completed":
            completed += 1
        elif p.project_status == "In Progress":
            in_progress += 1
        elif p.project_status == "Not Started":
            not_started += 1

    employee_usernames = db.query(ProjectTimer.employee_username).filter(
        ProjectTimer.project_id.in_(all_project_ids)
    ).distinct().all()
    employee_usernames = [u[0] for u in employee_usernames]

    return {
        "client": {
            "id": client.id,
            "client_name": client.client_name
        },
        "total_projects": total_projects,
        "completed": completed,
        "in_progress": in_progress,
        "not_started": not_started,
        "assigned_employees": employee_usernames,
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        }
    }


# ----- Client dashboard (for role "Client" – their projects) -----
@router.get("/client-dashboard")
def client_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ("Client", "Admin"):
        raise HTTPException(status_code=403, detail="Access denied")

    projects = db.query(Project).filter(Project.project_client == current_user.username).all()
    total_projects = len(projects)
    completed_projects = len([p for p in projects if p.project_status == "Completed"])
    ongoing_projects = len([p for p in projects if p.project_status == "In Progress"])

    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        },
        "projects": [
            {
                "id": p.id,
                "project_code": p.project_code,
                "project_name": p.project_name,
                "project_status": p.project_status,
                "project_type_name": p.project_type_name,
                "assigned_persons": p.assigned_persons,
                "project_note": p.project_note,
                "client_id": p.client_id,
                "project_client": p.project_client
            }
            for p in projects
        ],
        "total_projects": total_projects,
        "completed_projects": completed_projects,
        "ongoing_projects": ongoing_projects
    }


# ----- Client projects list -----
@router.get("/client-projects")
def client_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ("Admin", "Client"):
        raise HTTPException(status_code=403, detail="Access denied")

    projects = db.query(Project).filter(Project.project_client == current_user.first_name).all()

    return {
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role
        },
        "projects": [
            {
                "id": p.id,
                "project_code": p.project_code,
                "project_name": p.project_name,
                "project_status": p.project_status,
                "project_type_name": p.project_type_name,
                "assigned_persons": p.assigned_persons,
                "project_note": p.project_note,
                "client_id": p.client_id,
                "project_client": p.project_client
            }
            for p in projects
        ]
    }
