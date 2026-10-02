from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from utils.datetime_utils import ist_now
from database import get_db
from models.CampaignModel import Campaign
from models.UsersModel import User
from models.LeadsModel import Lead
from schemas.CampaignSchema import CampaignCreate, CampaignUpdate, CampaignOut
from routers.auth import get_current_user, get_admin_user

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])

# Create a new campaign
@router.post("/create-campaign", response_model=CampaignOut)
def create_campaign(data: CampaignCreate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):

    campaign = Campaign(
        name=data.name,
        ad_name=data.ad_name,
        platform=data.platform,
        start_date=data.start_date,
        end_date=data.end_date,
        budget=data.budget,
        status=data.status,
        manager_id=data.manager_id,
        description=data.description,
        created_at=ist_now().date()
    )

    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    return campaign


# Get all campaigns with optional filters
@router.get("/campaigns-list", response_model=List[CampaignOut])
def list_campaigns(
    db: Session = Depends(get_db),
    platform: Optional[str] = None,
    manager_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 20
):
    query = db.query(Campaign).filter(Campaign.is_deleted == False)

    if platform:
        query = query.filter(Campaign.platform == platform)

    if manager_id:
        query = query.filter(Campaign.manager_id == manager_id)

    if status:
        query = query.filter(Campaign.status == status)

    if search:
        from sqlalchemy import or_
        query = query.filter(
            or_(
                Campaign.name.ilike(f"%{search}%"),
                Campaign.ad_name.ilike(f"%{search}%")
            )
        )

    query = query.order_by(Campaign.created_at.desc())

    return query.offset(skip).limit(limit).all()

# Get a single campaign by ID
@router.get("/get-campaign/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.is_deleted == False).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    return campaign


# Update an existing campaign
@router.put("/update-campaign/{campaign_id}", response_model=CampaignOut)
def update_campaign(
    campaign_id: int,
    data: CampaignUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.is_deleted == False).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    for key, value in data.dict(exclude_unset=True).items():
        setattr(campaign, key, value)

    campaign.updated_at = ist_now()

    db.commit()
    db.refresh(campaign)
    return campaign

# Delete a campaign (soft delete)
@router.delete("/delete-campaign/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.is_deleted == False).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    campaign.is_deleted = True
    campaign.deleted_at = ist_now()
    db.commit()
    return {"message": "Campaign deleted successfully"}


# Hard delete a campaign (Admin only)
@router.delete("/delete-campaign/{campaign_id}/hard-delete")
def hard_delete_campaign(campaign_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    db.delete(campaign)
    db.commit()
    return {"message": "Campaign permanently deleted"}


# Assign a campaign manager
@router.post("/assign-campaign-manager/{campaign_id}")
def assign_campaign_manager(
    campaign_id: int,
    manager_id: int = Query(...),
    db: Session = Depends(get_db)
):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.is_deleted == False).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    manager = db.query(User).filter(User.id == manager_id, User.is_deleted == False).first()
    if not manager:
        raise HTTPException(404, "Manager not found")

    campaign.campaign_manager_id = manager_id
    db.commit()

    return {"message": "Campaign manager assigned"}


# Update campaign budget and spend
@router.post("/update-budget/{campaign_id}")
def update_campaign_budget(
    campaign_id: int,
    budget: Optional[float] = None,
    spend: Optional[float] = None,
    db: Session = Depends(get_db)
):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    if budget is not None:
        campaign.budget = budget
    if spend is not None:
        campaign.spent = spend

    db.commit()
    return {"message": "Updated successfully"}


# Update campaign status
@router.post("/update-status/{campaign_id}")
def update_campaign_status(
    campaign_id: int,
    status: str = Query(...),
    db: Session = Depends(get_db)
):
    valid_status = ["Active", "Paused", "Completed"]
    if status not in valid_status:
        raise HTTPException(400, "Invalid campaign status")

    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    campaign.status = status
    db.commit()
    return {"message": "Status updated"}



# Get campaign analytics
@router.get("/{campaign_id}/analytics")
def campaign_analytics(campaign_id: int, db: Session = Depends(get_db)):

    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    leads_count = db.query(Lead).filter(Lead.campaign_id == campaign_id).count()

    ctr = campaign.clicks / campaign.impressions * 100 if campaign.impressions else 0
    cpc = campaign.spent / campaign.clicks if campaign.clicks else 0
    cpl = campaign.spent / leads_count if leads_count else 0
    roas = (campaign.revenue / campaign.spent) if campaign.spent else 0

    return {
        "impressions": campaign.impressions,
        "clicks": campaign.clicks,
        "ctr": round(ctr, 2),
        "cpc": round(cpc, 2),
        "cpl": round(cpl, 2),
        "roas": round(roas, 2),
        "leads_generated": leads_count
    }
