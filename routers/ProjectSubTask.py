from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from database import get_db
from models.ProjectSubtaskModel import ProjectSubtask, SubtaskLog, SubtaskAttachment, SubtaskComment
from routers.auth import get_current_user
from models.ProjectModel import Project
from datetime import datetime
from utils.datetime_utils import ist_now
import os
import shutil
from pydantic import BaseModel


router = APIRouter()


class SubtaskCreate(BaseModel):
    title: str
    assigned_to: str = None


class SubtaskStatusUpdate(BaseModel):
    new_status: str


class CommentCreate(BaseModel):
    comment_text: str


# Add sub task to project
@router.post("/project/{project_code}/add-subtask")
def add_subtask(
    project_code: str,
    subtask_data: SubtaskCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    project = db.query(Project).filter(Project.project_code == project_code).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    assigned_to = subtask_data.assigned_to
    if current_user.role == "Employee":
        assigned_to = current_user.username

    subtask = ProjectSubtask(project_id=project.id, title=subtask_data.title, assigned_to=assigned_to)
    db.add(subtask)
    db.commit()
    db.refresh(subtask)
    
    return {
        "message": "Subtask added successfully",
        "subtask": {
            "id": subtask.id,
            "title": subtask.title,
            "status": subtask.status,
            "assigned_to": subtask.assigned_to,
            "project_id": subtask.project_id
        }
    }


# Update Sub task status
@router.post("/subtask/{subtask_id}/update-status")
def update_subtask_status(
    subtask_id: int,
    status_data: SubtaskStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    subtask = db.query(ProjectSubtask).filter(ProjectSubtask.id == subtask_id).first()
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")

    if current_user.role == "Employee":
        if subtask.assigned_to is None or subtask.assigned_to.strip().lower() != current_user.username.strip().lower():
            raise HTTPException(status_code=403, detail="Not allowed")

    old_status = subtask.status
    if old_status != status_data.new_status:
        subtask.status = status_data.new_status
        log = SubtaskLog(
            subtask_id=subtask.id,
            old_status=old_status,
            new_status=status_data.new_status,
            updated_by=f"{current_user.first_name} {current_user.last_name}",
            timestamp=ist_now()
        )
        db.add(log)

    db.commit()

    project = db.query(Project).filter(Project.id == subtask.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return {
        "message": "Subtask status updated successfully",
        "subtask": {
            "id": subtask.id,
            "title": subtask.title,
            "status": subtask.status,
            "assigned_to": subtask.assigned_to
        },
        "project_code": project.project_code
    }


# Add comments to subtask
@router.post("/subtask/{subtask_id}/add-comment")
def add_comment(
    subtask_id: int,
    comment_data: CommentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    subtask = db.query(ProjectSubtask).filter(ProjectSubtask.id == subtask_id).first()
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")

    comment = SubtaskComment(
        subtask_id=subtask.id,
        comment_text=comment_data.comment_text,
        created_by=f"{current_user.first_name} {current_user.last_name}",
        commented_at=ist_now()
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    project = db.query(Project).filter(Project.id == subtask.project_id).first()
    
    return {
        "message": "Comment added successfully",
        "comment": {
            "id": comment.id,
            "subtask_id": comment.subtask_id,
            "comment_text": comment.comment_text,
            "created_by": comment.created_by,
            "commented_at": comment.commented_at.isoformat() if comment.commented_at else None
        },
        "project_code": project.project_code if project else None
    }


# Subtask Upload file
@router.post("/subtask/{subtask_id}/upload-file")
def upload_file(
    subtask_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    subtask = db.query(ProjectSubtask).filter(ProjectSubtask.id == subtask_id).first()
    if not subtask or not subtask.project:
        raise HTTPException(status_code=404, detail="Subtask or related project not found")

    upload_dir = f"static/uploads/subtask_{subtask_id}"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    attachment = SubtaskAttachment(
        subtask_id=subtask_id,
        filename=file.filename,
        filepath=file_path,
        uploaded_by=f"{current_user.first_name} {current_user.last_name}",
        uploaded_at=ist_now()
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    return {
        "message": "File uploaded successfully",
        "attachment": {
            "id": attachment.id,
            "subtask_id": attachment.subtask_id,
            "filename": attachment.filename,
            "filepath": attachment.filepath,
            "uploaded_by": attachment.uploaded_by,
            "uploaded_at": attachment.uploaded_at.isoformat() if attachment.uploaded_at else None
        },
        "project_code": subtask.project.project_code
    }
