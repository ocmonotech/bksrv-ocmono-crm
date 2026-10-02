from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models.ProjectModel import Project
from dependencies import get_current_user  # Assuming session-based auth

router = APIRouter()

@router.get("/employee-projects")
def employee_projects(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    projects = db.query(Project).filter(Project.assigned_persons.like(f"%{current_user['first_name']}%")).all()
    
    return {
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
                "project_client": p.project_client,
                "total_time_spent": p.total_time_spent
            }
            for p in projects
        ]
    }
