from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from database import get_db
from routers.auth import get_current_user, get_admin_user
from models.UsersModel import User
from models.MessageTemplateModel import MessageTemplate
from utils.activity import set_activity_description, describe_created, describe_updated, describe_deleted
from schemas.MessageTemplateSchema import (
    MessageTemplateCreate, 
    MessageTemplateUpdate, 
    MessageTemplateOut,
    TemplateAnalytics,
    TemplateUsageStats,
    UsageByType
)
from typing import List, Optional
from datetime import datetime
from utils.datetime_utils import ist_now


router = APIRouter(prefix="/communications", tags=["Communications"])


# Create a new message template
@router.post("/templates/create", response_model=MessageTemplateOut)
def create_template(request: Request, data: MessageTemplateCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    template_data = data.dict()
    # Extract variables from content if not provided
    if not template_data.get('variables') and template_data.get('content'):
        import re
        variables = re.findall(r'\{\{(\w+)\}\}', template_data['content'])
        template_data['variables'] = list(set(variables))
    
    template = MessageTemplate(**template_data)
    db.add(template)
    db.commit()
    db.refresh(template)
    set_activity_description(request, describe_created("message template", template.name or f"#{template.id}"))
    return template


# Get all templates with search and filters
@router.get("/templates", response_model=List[MessageTemplateOut])
def get_all_templates(
    search: Optional[str] = Query(None, description="Search by name, content, or tags"),
    template_type: Optional[str] = Query(None, description="Filter by type: email, whatsapp, sms"),
    category: Optional[str] = Query(None, description="Filter by category"),
    status: Optional[str] = Query(None, description="Filter by status: Draft, Active"),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(MessageTemplate).filter(MessageTemplate.is_deleted == False)
    
    # Search filter
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                MessageTemplate.name.ilike(search_term),
                MessageTemplate.content.ilike(search_term),
                MessageTemplate.subject.ilike(search_term)
            )
        )
    
    # Type filter
    if template_type:
        query = query.filter(MessageTemplate.template_type == template_type.lower())
    
    # Category filter
    if category:
        query = query.filter(MessageTemplate.category == category)
    
    # Status filter
    if status:
        query = query.filter(MessageTemplate.status == status)
    
    query = query.order_by(MessageTemplate.created_at.desc())
    
    return query.offset(skip).limit(limit).all()


# Get a single template by ID
@router.get("/templates/{template_id}", response_model=MessageTemplateOut)
def get_template(template_id: int, db: Session = Depends(get_db)):
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id, MessageTemplate.is_deleted == False).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


# Update a template
@router.put("/templates/{template_id}", response_model=MessageTemplateOut)
def update_template(
    request: Request,
    template_id: int, 
    data: MessageTemplateUpdate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id, MessageTemplate.is_deleted == False).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    update_data = data.dict(exclude_unset=True)
    
    # Extract variables from content if content is updated
    if 'content' in update_data and not update_data.get('variables'):
        import re
        variables = re.findall(r'\{\{(\w+)\}\}', update_data['content'])
        update_data['variables'] = list(set(variables))
    
    # Increment version if content or subject changes
    if 'content' in update_data or 'subject' in update_data:
        # Extract version number and increment
        current_version = template.version or "v1"
        if current_version.startswith('v'):
            try:
                version_num = int(current_version[1:])
                update_data['version'] = f"v{version_num + 1}"
            except:
                update_data['version'] = "v2"
        else:
            update_data['version'] = "v2"
    
    for key, value in update_data.items():
        setattr(template, key, value)
    
    template.updated_at = ist_now()
    db.commit()
    db.refresh(template)
    changed = ", ".join(update_data.keys()) or "details"
    set_activity_description(request, describe_updated("message template", template.name or f"#{template_id}", changed))
    return template


# Delete a template (soft delete)
@router.delete("/templates/{template_id}")
def delete_template(request: Request, template_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id, MessageTemplate.is_deleted == False).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    name = template.name
    template.is_deleted = True
    template.deleted_at = ist_now()
    db.commit()
    set_activity_description(request, describe_deleted("message template", name or f"#{template_id}"))
    return {"detail": "Template deleted successfully"}


# Hard delete a template (Admin only)
@router.delete("/templates/{template_id}/hard-delete")
def hard_delete_template(request: Request, template_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    name = template.name
    db.delete(template)
    db.commit()
    set_activity_description(request, describe_deleted("message template (hard)", name or f"#{template_id}"))
    return {"detail": "Template permanently deleted"}


# Track template usage (call this when a template is used)
@router.post("/templates/{template_id}/track-usage")
def track_template_usage(
    template_id: int,
    success: bool = Query(True, description="Whether the message was sent successfully"),
    db: Session = Depends(get_db)
):
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id, MessageTemplate.is_deleted == False).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    template.usage_count += 1
    if success:
        template.success_count += 1
    
    # Calculate success rate
    if template.usage_count > 0:
        template.success_rate = (template.success_count / template.usage_count) * 100
    
    db.commit()
    db.refresh(template)
    return {"detail": "Usage tracked", "usage_count": template.usage_count, "success_rate": template.success_rate}


# Get template analytics
@router.get("/templates/analytics", response_model=TemplateAnalytics)
def get_template_analytics(db: Session = Depends(get_db)):
    total_templates = db.query(MessageTemplate).count()
    total_usage = db.query(func.sum(MessageTemplate.usage_count)).scalar() or 0
    active_templates = db.query(MessageTemplate).filter(MessageTemplate.status == "Active").count()
    
    # Calculate average success rate
    templates_with_usage = db.query(MessageTemplate).filter(MessageTemplate.usage_count > 0).all()
    if templates_with_usage:
        avg_success_rate = sum(t.success_rate for t in templates_with_usage) / len(templates_with_usage)
    else:
        avg_success_rate = 0.0
    
    return {
        "total_templates": total_templates,
        "total_usage": total_usage,
        "avg_success_rate": round(avg_success_rate, 1),
        "active_templates": active_templates
    }


# Get most used templates
@router.get("/templates/analytics/most-used", response_model=List[TemplateUsageStats])
def get_most_used_templates(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    templates = db.query(MessageTemplate)\
        .order_by(MessageTemplate.usage_count.desc())\
        .limit(limit)\
        .all()
    
    return [
        TemplateUsageStats(
            template_id=t.id,
            template_name=t.name,
            usage=t.usage_count,
            success_rate=t.success_rate
        )
        for t in templates
    ]


# Get usage by type
@router.get("/templates/analytics/usage-by-type", response_model=List[UsageByType])
def get_usage_by_type(db: Session = Depends(get_db)):
    results = db.query(
        MessageTemplate.template_type,
        func.sum(MessageTemplate.usage_count).label('total_usage'),
        func.count(MessageTemplate.id).label('templates')
    ).group_by(MessageTemplate.template_type).all()
    
    return [
        UsageByType(
            template_type=r.template_type.upper(),
            total_usage=int(r.total_usage or 0),
            templates=r.templates
        )
        for r in results
    ]