from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request, Header
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc
from database import get_db
from models.UsersModel import User
from models.LeadsModel import Lead
from models.NewsletterModel import Newsletter, NewsletterEmailLog, DailyEmailLimit, NewsletterUnsubscribe
from models.MessageTemplateModel import MessageTemplate
from models.CampaignModel import Campaign
from schemas.NewsletterSchema import (
    NewsletterCreate, NewsletterUpdate, NewsletterOut,
    NewsletterPreviewRequest, NewsletterPreviewResponse,
    NewsletterEmailLogOut, DailyEmailLimitOut, NewsletterStatsOut,
    NewsletterUnsubscribeRequest, NewsletterWebhookPayload
)
from routers.auth import get_current_user, get_admin_user, SECRET_KEY, ALGORITHM
from routers.Notification import send_email
from typing import List, Optional, Tuple
from datetime import datetime, timedelta, date, timezone
from utils.datetime_utils import IST, ist_now, ist_today
import os
import re
import time
import logging
import traceback
import uuid
import hmac
import hashlib
import threading
from jose import jwt, JWTError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/newsletters", tags=["Newsletters"])

_NEWSLETTER_SEND_LOCK = threading.Lock()
_ACTIVE_NEWSLETTER_SEND_IDS: set[int] = set()

# Log rows still waiting for SMTP for this newsletter (incl. paused on daily cap)
_LOG_NEEDS_SMTP = frozenset({"queued"})
# Log rows that finished the send pipeline (no more SMTP for this recipient)
_LOG_SEND_TERMINAL = frozenset(
    {"sent", "delivered", "opened", "clicked", "failed", "bounced", "complained", "unsubscribed"}
)
_DAILY_LIMIT_MSG = "Daily email limit reached (sending resumes automatically when quota resets)"


def replace_newsletter_variables(content: str, lead_data: dict) -> str:
    """Replace template variables with actual lead data"""
    replacements = {
        '{{name}}': lead_data.get('name', ''),
        '{{email}}': lead_data.get('email', ''),
        '{{phone}}': lead_data.get('phone', ''),
        '{{company}}': lead_data.get('company', ''),
        '{{campaign}}': lead_data.get('campaign', ''),
        '{{value}}': str(lead_data.get('value', '')),
        '{{city}}': lead_data.get('city', ''),
        '{{source}}': lead_data.get('source', ''),
        '{{status}}': lead_data.get('status', ''),
    }
    
    result = content
    for var, value in replacements.items():
        result = result.replace(var, str(value))
    
    # Also handle any other variables in the format {{variable_name}}
    def replace_var(match):
        var_name = match.group(1).lower()
        return str(lead_data.get(var_name, ''))
    
    result = re.sub(r'\{\{(\w+)\}\}', replace_var, result)
    
    return result


def get_daily_email_count(db: Session, target_date: date = None, newsletter_id: Optional[int] = None) -> int:
    """Count successful SMTP sends today (IST). If newsletter_id is set, only that newsletter's logs."""
    if target_date is None:
        target_date = ist_today()

    date_start = datetime.combine(target_date, datetime.min.time(), tzinfo=IST)
    date_end = datetime.combine(target_date, datetime.max.time(), tzinfo=IST)

    q = db.query(func.count(NewsletterEmailLog.id)).filter(
        NewsletterEmailLog.sent_at.isnot(None),
        NewsletterEmailLog.sent_at >= date_start,
        NewsletterEmailLog.sent_at <= date_end,
    )
    if newsletter_id is not None:
        q = q.filter(NewsletterEmailLog.newsletter_id == newsletter_id)

    return q.scalar() or 0


def can_send_email(
    db: Session, daily_limit: int = 100, newsletter_id: Optional[int] = None
) -> Tuple[bool, int]:
    """Check daily send quota (per newsletter when newsletter_id is passed)."""
    today_count = get_daily_email_count(db, newsletter_id=newsletter_id)
    return (today_count < daily_limit, today_count)


def _latest_log_for_lead(db: Session, newsletter_id: int, lead_id: int) -> Optional[NewsletterEmailLog]:
    return (
        db.query(NewsletterEmailLog)
        .filter(
            NewsletterEmailLog.newsletter_id == newsletter_id,
            NewsletterEmailLog.lead_id == lead_id,
        )
        .order_by(desc(NewsletterEmailLog.id))
        .first()
    )


def _eligible_leads_for_newsletter(db: Session, newsletter: Newsletter) -> List[Lead]:
    return (
        db.query(Lead)
        .filter(
            Lead.id.in_(newsletter.lead_ids),
            Lead.is_deleted == False,
            Lead.email.isnot(None),
            Lead.email != "",
            or_(Lead.is_unsubscribed == False, Lead.is_unsubscribed.is_(None)),
        )
        .all()
    )


def _leads_pending_send(db: Session, newsletter: Newsletter, eligible_leads: List[Lead]) -> List[Lead]:
    """Leads still waiting for an SMTP attempt (no terminal log, or still queued)."""
    eligible_by_id = {l.id: l for l in eligible_leads}
    pending: List[Lead] = []
    for lid in newsletter.lead_ids or []:
        if lid not in eligible_by_id:
            continue
        log = _latest_log_for_lead(db, newsletter.id, lid)
        if log is None or log.status in _LOG_NEEDS_SMTP:
            pending.append(eligible_by_id[lid])
    return pending


def _is_newsletter_send_complete(db: Session, newsletter_id: int) -> bool:
    nl = db.query(Newsletter).filter(Newsletter.id == newsletter_id).first()
    if not nl:
        return True
    eligible = _eligible_leads_for_newsletter(db, nl)
    if not eligible:
        return True
    for lead in eligible:
        log = _latest_log_for_lead(db, newsletter_id, lead.id)
        if log is None or log.status not in _LOG_SEND_TERMINAL:
            return False
    return True


def _rollup_newsletter_send_counts(db: Session, newsletter: Newsletter) -> None:
    nid = newsletter.id
    sent_n = (
        db.query(func.count(NewsletterEmailLog.id))
        .filter(
            NewsletterEmailLog.newsletter_id == nid,
            NewsletterEmailLog.sent_at.isnot(None),
        )
        .scalar()
        or 0
    )
    failed_n = (
        db.query(func.count(NewsletterEmailLog.id))
        .filter(
            NewsletterEmailLog.newsletter_id == nid,
            NewsletterEmailLog.status == "failed",
        )
        .scalar()
        or 0
    )
    newsletter.sent_count = sent_n
    newsletter.failed_count = failed_n


def _ensure_queued_log(
    db: Session,
    newsletter_id: int,
    lead: Lead,
    error_message: str,
) -> NewsletterEmailLog:
    log = _latest_log_for_lead(db, newsletter_id, lead.id)
    if log and log.status in _LOG_SEND_TERMINAL:
        return log
    if not log:
        log = NewsletterEmailLog(
            newsletter_id=newsletter_id,
            lead_id=lead.id,
            lead_email=lead.email,
            lead_name=lead.name,
        )
        db.add(log)
    log.status = "queued"
    log.error_message = error_message
    log.last_event_at = ist_now()
    return log


STATUS_RANK = {
    "queued": 0,
    "sent": 1,
    "delivered": 2,
    "opened": 3,
    "clicked": 4,
    "failed": 5,
    "bounced": 6,
    "complained": 7,
    "unsubscribed": 8,
}


def _validate_selected_lead_ids(db: Session, lead_ids: List[int]) -> List[int]:
    """Validate selected lead IDs and return unique IDs preserving order."""
    if not lead_ids:
        raise HTTPException(status_code=400, detail="At least one lead must be selected")

    # De-duplicate while preserving the original order from payload.
    unique_lead_ids = list(dict.fromkeys(lead_ids))

    leads = db.query(Lead).filter(Lead.id.in_(unique_lead_ids)).all()
    lead_by_id = {lead.id: lead for lead in leads}

    missing_ids = [lead_id for lead_id in unique_lead_ids if lead_id not in lead_by_id]
    deleted_ids = [lead_id for lead_id in unique_lead_ids if lead_id in lead_by_id and lead_by_id[lead_id].is_deleted]
    unsubscribed_ids = [
        lead_id for lead_id in unique_lead_ids if lead_id in lead_by_id and bool(lead_by_id[lead_id].is_unsubscribed)
    ]

    if missing_ids or deleted_ids or unsubscribed_ids:
        parts = []
        if missing_ids:
            parts.append(f"missing: {missing_ids}")
        if deleted_ids:
            parts.append(f"deleted: {deleted_ids}")
        if unsubscribed_ids:
            parts.append(f"unsubscribed: {unsubscribed_ids}")
        raise HTTPException(
            status_code=400,
            detail=f"Some selected leads are not eligible ({'; '.join(parts)})",
        )

    return unique_lead_ids


def _create_unsubscribe_token(lead_id: int, newsletter_id: int, email: str) -> str:
    payload = {
        "lead_id": lead_id,
        "newsletter_id": newsletter_id,
        "email": email,
        "exp": ist_now() + timedelta(days=30),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _build_unsubscribe_url(lead_id: int, newsletter_id: int, email: str) -> str:
    base = (os.getenv("FRONTEND_BASE_URL") or os.getenv("PUBLIC_APP_URL") or "").rstrip("/")
    token = _create_unsubscribe_token(lead_id, newsletter_id, email)
    if not base:
        return f"/unsubscribe?token={token}"
    return f"{base}/unsubscribe?token={token}"


def _unsubscribe_footer_html(lead_id: int, newsletter_id: int, email: str) -> str:
    url = _build_unsubscribe_url(lead_id, newsletter_id, email)
    return (
        f'<p style="font-size:12px;color:#666;margin-top:1.5em;">'
        f'<a href="{url}">Unsubscribe</a> from this mailing list.</p>'
    )


def _unsubscribe_footer_plain(lead_id: int, newsletter_id: int, email: str) -> str:
    url = _build_unsubscribe_url(lead_id, newsletter_id, email)
    return f"\n\nUnsubscribe from this mailing list: {url}"


def _apply_event_status(log: NewsletterEmailLog, event_status: str, event_at: datetime) -> None:
    current_rank = STATUS_RANK.get(log.status or "queued", -1)
    incoming_rank = STATUS_RANK.get(event_status, -1)
    if incoming_rank >= current_rank:
        log.status = event_status

    if event_status == "delivered":
        log.delivered_at = event_at
    elif event_status == "opened":
        log.opened_at = event_at
        log.open_count = (log.open_count or 0) + 1
    elif event_status == "clicked":
        log.clicked_at = event_at
        log.click_count = (log.click_count or 0) + 1
    elif event_status == "failed":
        log.failed_at = event_at
    elif event_status == "bounced":
        log.bounced_at = event_at
    elif event_status == "unsubscribed":
        log.unsubscribed_at = event_at
    log.last_event_at = event_at


def send_newsletter_emails(newsletter_id: int):
    """Background: send in batches; may pause on daily cap (status Sending) and resume next day via scheduler."""
    from database import SessionLocal

    with _NEWSLETTER_SEND_LOCK:
        if newsletter_id in _ACTIVE_NEWSLETTER_SEND_IDS:
            logger.info("Newsletter %s send already in progress; skip duplicate", newsletter_id)
            return
        _ACTIVE_NEWSLETTER_SEND_IDS.add(newsletter_id)

    db = SessionLocal()
    try:
        newsletter = db.query(Newsletter).filter(Newsletter.id == newsletter_id, Newsletter.is_deleted == False).first()
        if not newsletter:
            print(f"⚠️  Newsletter {newsletter_id} not found")
            return

        if newsletter.status == "Sent" and not _is_newsletter_send_complete(db, newsletter_id):
            newsletter.status = "Sending"
            db.commit()
        elif newsletter.status == "Sent":
            print(f"⚠️  Newsletter {newsletter_id} already fully sent")
            return

        eligible_leads = _eligible_leads_for_newsletter(db, newsletter)
        if not eligible_leads:
            print(f"⚠️  No leads found for newsletter {newsletter_id}")
            return

        newsletter.total_recipients = len(eligible_leads)
        pending = _leads_pending_send(db, newsletter, eligible_leads)

        if not pending:
            _rollup_newsletter_send_counts(db, newsletter)
            newsletter.status = "Sent"
            if newsletter.sent_at is None:
                newsletter.sent_at = ist_now()
            db.commit()
            print(f"✓ Newsletter {newsletter_id}: nothing pending, marked Sent")
            return

        daily_limit = newsletter.daily_email_limit or 100
        can_send, used = can_send_email(db, daily_limit, newsletter.id)
        if not can_send:
            logger.info(
                "Newsletter %s: daily cap for this newsletter already used (%s/%s); will retry later",
                newsletter_id,
                used,
                daily_limit,
            )
            _rollup_newsletter_send_counts(db, newsletter)
            newsletter.status = "Sending"
            db.commit()
            return

        newsletter.status = "Sending"
        db.commit()

        batch_size = max(1, newsletter.per_hour_limit or 50)
        batch_interval_sec = max(0, (newsletter.batch_interval_minutes or 30) * 60)

        send_kw = {}
        if newsletter.send_from_email:
            send_kw["from_email"] = newsletter.send_from_email
        if newsletter.send_from_name:
            send_kw["from_name"] = newsletter.send_from_name
        if newsletter.reply_to_email:
            send_kw["reply_to"] = newsletter.reply_to_email
        if newsletter.tracking_campaign_name:
            send_kw["campaign_tracking_name"] = newsletter.tracking_campaign_name

        template = None
        if newsletter.template_id:
            template = db.query(MessageTemplate).filter(MessageTemplate.id == newsletter.template_id).first()

        base_content = template.content if template else newsletter.content
        base_subject = template.subject if template and template.subject else newsletter.subject

        n = len(pending)
        pos = 0
        stopped_on_daily_cap = False

        while pos < n:
            batch_end = min(pos + batch_size, n)
            for i in range(pos, batch_end):
                lead = pending[i]
                can_send_now, _ = can_send_email(db, daily_limit, newsletter.id)
                if not can_send_now:
                    print(f"⚠️  Daily email limit ({daily_limit}) reached for newsletter {newsletter_id}. Pausing.")
                    for j in range(i, n):
                        _ensure_queued_log(db, newsletter_id, pending[j], _DAILY_LIMIT_MSG)
                    stopped_on_daily_cap = True
                    break

                provider_message_id = str(uuid.uuid4())
                email_log = _latest_log_for_lead(db, newsletter_id, lead.id)
                if not email_log:
                    email_log = NewsletterEmailLog(
                        newsletter_id=newsletter_id,
                        lead_id=lead.id,
                        lead_email=lead.email,
                        lead_name=lead.name,
                    )
                    db.add(email_log)
                email_log.status = "queued"
                email_log.provider_message_id = provider_message_id
                email_log.error_message = None
                email_log.last_event_at = ist_now()
                db.commit()

                try:
                    campaign_name = ""
                    if lead.campaign_id:
                        campaign = db.query(Campaign).filter(Campaign.id == lead.campaign_id).first()
                        if campaign:
                            campaign_name = campaign.name or ""

                    lead_data = {
                        "name": lead.name or "",
                        "email": lead.email or "",
                        "phone": lead.phone or "",
                        "company": campaign_name,
                        "campaign": campaign_name,
                        "value": "",
                        "city": lead.city or "",
                        "source": lead.source or "",
                        "status": lead.status or "",
                    }

                    email_content = replace_newsletter_variables(base_content, lead_data)
                    email_subject = replace_newsletter_variables(base_subject, lead_data)

                    if newsletter.content_type == "html":
                        html_body = email_content
                    else:
                        html_body = f"<pre style='font-family: Arial, sans-serif;'>{email_content}</pre>"

                    if getattr(newsletter, "include_unsubscribe", True):
                        html_body = html_body + _unsubscribe_footer_html(lead.id, newsletter_id, lead.email)
                        if newsletter.content_type != "html":
                            html_body = html_body + _unsubscribe_footer_plain(lead.id, newsletter_id, lead.email)

                    success, send_err = send_email(lead.email, email_subject, html_body, **send_kw)

                    email_log = _latest_log_for_lead(db, newsletter_id, lead.id) or email_log
                    email_log.status = "sent" if success else "failed"
                    email_log.sent_at = ist_now() if success else None
                    email_log.failed_at = ist_now() if not success else None
                    email_log.error_message = None if success else (send_err or "Email sending failed")
                    email_log.last_event_at = ist_now()
                    db.commit()

                except Exception as e:
                    print(f"✗ Error sending email to {lead.email}: {e}")
                    email_log = _latest_log_for_lead(db, newsletter_id, lead.id)
                    if not email_log:
                        email_log = NewsletterEmailLog(
                            newsletter_id=newsletter_id,
                            lead_id=lead.id,
                            lead_email=lead.email,
                            lead_name=lead.name,
                        )
                        db.add(email_log)
                    email_log.status = "failed"
                    email_log.failed_at = ist_now()
                    email_log.error_message = str(e)
                    email_log.last_event_at = ist_now()
                    db.commit()

            if stopped_on_daily_cap:
                break
            pos = batch_end
            if pos < n and batch_interval_sec > 0:
                time.sleep(batch_interval_sec)

        db.refresh(newsletter)
        _rollup_newsletter_send_counts(db, newsletter)
        if _is_newsletter_send_complete(db, newsletter_id):
            newsletter.status = "Sent"
            if newsletter.sent_at is None:
                newsletter.sent_at = ist_now()
        else:
            newsletter.status = "Sending"
        db.commit()

        print(
            f"✓ Newsletter {newsletter_id} batch done "
            f"(status={newsletter.status}, sent={newsletter.sent_count}, failed={newsletter.failed_count})"
        )

    except Exception as e:
        print(f"✗ Error sending newsletter {newsletter_id}: {e}")
        traceback.print_exc()
    finally:
        db.close()
        with _NEWSLETTER_SEND_LOCK:
            _ACTIVE_NEWSLETTER_SEND_IDS.discard(newsletter_id)


# Create newsletter
@router.post("/create-newsletter", response_model=NewsletterOut)
def create_newsletter(
    data: NewsletterCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new newsletter"""
    try:
        return _create_newsletter_impl(data, background_tasks, db, current_user)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("create_newsletter failed")
        detail = {
            "detail": "Failed to create newsletter",
            "error": type(e).__name__,
            "message": str(e) or repr(e),
        }
        if os.getenv("NEWSLETTER_ERROR_TRACEBACK", "").lower() in ("1", "true", "yes"):
            detail["traceback"] = traceback.format_exc()
        raise HTTPException(status_code=500, detail=detail)


def _create_newsletter_impl(
    data: NewsletterCreate,
    background_tasks: BackgroundTasks,
    db: Session,
    current_user: User,
):
    template = None
    if data.template_id:
        template = db.query(MessageTemplate).filter(
            MessageTemplate.id == data.template_id,
            MessageTemplate.template_type == "email"
        ).first()
        if not template:
            raise HTTPException(status_code=404, detail="Email template not found")
    
    subject = data.subject
    content = data.content
    if template:
        if not (subject or "").strip():
            subject = template.subject or ""
        if not (content or "").strip():
            content = template.content or ""
    
    if data.recipient_mode == "campaign":
        if not data.campaign_id:
            raise HTTPException(status_code=400, detail="campaign_id is required when sending to a campaign")
        campaign = db.query(Campaign).filter(
            Campaign.id == data.campaign_id,
            Campaign.is_deleted == False,
        ).first()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        campaign_leads = db.query(Lead).filter(
            Lead.campaign_id == data.campaign_id,
            Lead.is_deleted == False,
            Lead.email.isnot(None),
            Lead.email != "",
            or_(Lead.is_unsubscribed == False, Lead.is_unsubscribed.is_(None)),
        ).all()
        resolved_lead_ids = [l.id for l in campaign_leads]
        if not resolved_lead_ids:
            raise HTTPException(status_code=400, detail="No leads with an email address in this campaign")
    else:
        resolved_lead_ids = _validate_selected_lead_ids(db, data.lead_ids)
    
    effective_status = "Draft" if not data.send_now else data.status
    
    # Create newsletter
    newsletter = Newsletter(
        subject=subject,
        content=content,
        content_type=data.content_type,
        template_id=data.template_id,
        recipient_mode=data.recipient_mode,
        campaign_id=data.campaign_id if data.recipient_mode == "campaign" else None,
        lead_ids=resolved_lead_ids,
        status=effective_status,
        send_interval=data.send_interval,
        scheduled_at=data.scheduled_at,
        daily_email_limit=data.daily_email_limit,
        send_from_email=data.send_from_email,
        send_from_name=data.send_from_name,
        reply_to_email=data.reply_to_email,
        tracking_campaign_name=data.tracking_campaign_name,
        per_hour_limit=data.per_hour_limit,
        batch_interval_minutes=data.batch_interval_minutes,
        include_unsubscribe=data.include_unsubscribe,
        created_by_id=current_user.id,
        total_recipients=len(resolved_lead_ids)
    )
    
    db.add(newsletter)
    db.commit()
    db.refresh(newsletter)
    
    # If status is not Draft and scheduled_at is in the past or now, send immediately
    now_ist = ist_now()
    if data.send_now and effective_status != "Draft" and data.scheduled_at:
        scheduled_at_cmp = data.scheduled_at
        if scheduled_at_cmp.tzinfo is None:
            scheduled_at_cmp = scheduled_at_cmp.replace(tzinfo=IST)
        else:
            scheduled_at_cmp = scheduled_at_cmp.astimezone(IST)

        if scheduled_at_cmp <= now_ist:
            background_tasks.add_task(send_newsletter_emails, newsletter.id)
    elif data.send_now and effective_status != "Draft" and not data.scheduled_at:
        # No scheduled time, send immediately
        background_tasks.add_task(send_newsletter_emails, newsletter.id)
    
    # Format response
    template_name = None
    if newsletter.template_id:
        template = db.query(MessageTemplate).filter(MessageTemplate.id == newsletter.template_id).first()
        if template:
            template_name = template.name
    
    creator_name = f"{current_user.first_name} {current_user.last_name}".strip() or current_user.username
    
    return format_newsletter_out(newsletter, template_name, creator_name)


# Get all newsletters
@router.get("/all-newsletters", response_model=List[NewsletterOut])
def get_newsletters(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all newsletters with filters"""
    query = db.query(Newsletter).filter(Newsletter.is_deleted == False)
    
    if status:
        query = query.filter(Newsletter.status == status)
    
    if search:
        query = query.filter(
            or_(
                Newsletter.subject.ilike(f"%{search}%"),
                Newsletter.content.ilike(f"%{search}%")
            )
        )
    
    newsletters = query.order_by(desc(Newsletter.created_at)).offset(skip).limit(limit).all()
    
    result = []
    for newsletter in newsletters:
        template_name = None
        if newsletter.template_id:
            template = db.query(MessageTemplate).filter(MessageTemplate.id == newsletter.template_id).first()
            if template:
                template_name = template.name
        
        creator = db.query(User).filter(User.id == newsletter.created_by_id).first()
        creator_name = f"{creator.first_name} {creator.last_name}".strip() if creator else "Unknown"
        
        result.append(format_newsletter_out(newsletter, template_name, creator_name))
    
    return result


# Get newsletter by ID
@router.get("/get-newsletter/{newsletter_id}", response_model=NewsletterOut)
def get_newsletter(
    newsletter_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific newsletter"""
    newsletter = db.query(Newsletter).filter(Newsletter.id == newsletter_id, Newsletter.is_deleted == False).first()
    if not newsletter:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    
    template_name = None
    if newsletter.template_id:
        template = db.query(MessageTemplate).filter(MessageTemplate.id == newsletter.template_id).first()
        if template:
            template_name = template.name
    
    creator = db.query(User).filter(User.id == newsletter.created_by_id).first()
    creator_name = f"{creator.first_name} {creator.last_name}".strip() if creator else "Unknown"
    
    return format_newsletter_out(newsletter, template_name, creator_name)


# Update newsletter
@router.put("/update-newsletter/{newsletter_id}", response_model=NewsletterOut)
def update_newsletter(
    newsletter_id: int,
    data: NewsletterUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a newsletter"""
    newsletter = db.query(Newsletter).filter(Newsletter.id == newsletter_id, Newsletter.is_deleted == False).first()
    if not newsletter:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    
    if newsletter.status == "Sending":
        raise HTTPException(
            status_code=400,
            detail="Cannot update a newsletter while sending is in progress",
        )
    if newsletter.status == "Sent" and _is_newsletter_send_complete(db, newsletter_id):
        raise HTTPException(status_code=400, detail="Cannot update a completed newsletter")

    # Update fields
    if data.subject is not None:
        newsletter.subject = data.subject
    if data.content is not None:
        newsletter.content = data.content
    if data.content_type is not None:
        newsletter.content_type = data.content_type
    if data.template_id is not None:
        if data.template_id:
            template = db.query(MessageTemplate).filter(MessageTemplate.id == data.template_id).first()
            if not template:
                raise HTTPException(status_code=404, detail="Template not found")
        newsletter.template_id = data.template_id
    if data.lead_ids is not None:
        validated_lead_ids = _validate_selected_lead_ids(db, data.lead_ids)
        newsletter.lead_ids = validated_lead_ids
        newsletter.total_recipients = len(validated_lead_ids)
    if data.status is not None:
        newsletter.status = data.status
    if data.send_interval is not None:
        newsletter.send_interval = data.send_interval
    if data.scheduled_at is not None:
        newsletter.scheduled_at = data.scheduled_at
    if data.daily_email_limit is not None:
        newsletter.daily_email_limit = data.daily_email_limit
    if data.recipient_mode is not None:
        newsletter.recipient_mode = data.recipient_mode
    if data.campaign_id is not None:
        newsletter.campaign_id = data.campaign_id
    if data.send_from_email is not None:
        newsletter.send_from_email = data.send_from_email
    if data.send_from_name is not None:
        newsletter.send_from_name = data.send_from_name
    if data.reply_to_email is not None:
        newsletter.reply_to_email = data.reply_to_email
    if data.tracking_campaign_name is not None:
        newsletter.tracking_campaign_name = data.tracking_campaign_name
    if data.per_hour_limit is not None:
        newsletter.per_hour_limit = data.per_hour_limit
    if data.batch_interval_minutes is not None:
        newsletter.batch_interval_minutes = data.batch_interval_minutes
    if data.include_unsubscribe is not None:
        newsletter.include_unsubscribe = data.include_unsubscribe
    
    newsletter.updated_at = ist_now()
    db.commit()
    db.refresh(newsletter)
    
    template_name = None
    if newsletter.template_id:
        template = db.query(MessageTemplate).filter(MessageTemplate.id == newsletter.template_id).first()
        if template:
            template_name = template.name
    
    creator = db.query(User).filter(User.id == newsletter.created_by_id).first()
    creator_name = f"{creator.first_name} {creator.last_name}".strip() if creator else "Unknown"
    
    return format_newsletter_out(newsletter, template_name, creator_name)


# Delete newsletter (soft delete)
@router.delete("/delete-newsletter/{newsletter_id}")
def delete_newsletter(
    newsletter_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a newsletter"""
    newsletter = db.query(Newsletter).filter(Newsletter.id == newsletter_id, Newsletter.is_deleted == False).first()
    if not newsletter:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    newsletter.is_deleted = True
    newsletter.deleted_at = ist_now()
    db.commit()
    return {"message": "Newsletter deleted successfully"}


# Hard delete newsletter (Admin only)
@router.delete("/delete-newsletter/{newsletter_id}/hard-delete")
def hard_delete_newsletter(
    newsletter_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user)
):
    newsletter = db.query(Newsletter).filter(Newsletter.id == newsletter_id).first()
    if not newsletter:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    db.delete(newsletter)
    db.commit()
    return {"message": "Newsletter permanently deleted"}


# Preview newsletter
@router.post("/preview-newsletter", response_model=NewsletterPreviewResponse)
def preview_newsletter(
    data: NewsletterPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Preview newsletter with a specific lead's data"""
    lead = db.query(Lead).filter(Lead.id == data.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Get campaign name
    campaign_name = ""
    if lead.campaign_id:
        campaign = db.query(Campaign).filter(Campaign.id == lead.campaign_id).first()
        if campaign:
            campaign_name = campaign.name or ""
    
    lead_data = {
        'name': lead.name or '',
        'email': lead.email or '',
        'phone': lead.phone or '',
        'company': campaign_name,
        'campaign': campaign_name,
        'value': '',
        'city': lead.city or '',
        'source': lead.source or '',
        'status': lead.status or '',
    }
    
    # Replace variables
    preview_content = replace_newsletter_variables(data.content, lead_data)
    preview_subject = replace_newsletter_variables(data.subject, lead_data)
    
    return NewsletterPreviewResponse(
        subject=preview_subject,
        content=preview_content,
        lead_name=lead.name or '',
        lead_email=lead.email or ''
    )


# Send newsletter immediately
@router.post("/send-newsletter/{newsletter_id}", response_model=NewsletterOut)
def send_newsletter(
    newsletter_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Send newsletter immediately"""
    newsletter = db.query(Newsletter).filter(Newsletter.id == newsletter_id, Newsletter.is_deleted == False).first()
    if not newsletter:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    
    if newsletter.status == "Sent" and _is_newsletter_send_complete(db, newsletter_id):
        raise HTTPException(status_code=400, detail="Newsletter already fully sent")

    daily = newsletter.daily_email_limit or 100
    can_send, current_count = can_send_email(db, daily, newsletter.id)
    if not can_send:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Daily email limit for this newsletter reached today "
                f"({current_count}/{daily}). Sending resumes automatically when the quota resets."
            ),
        )

    # Start sending (first run or resume when status is Sending / Scheduled / Draft)
    background_tasks.add_task(send_newsletter_emails, newsletter_id)
    
    db.refresh(newsletter)
    
    template_name = None
    if newsletter.template_id:
        template = db.query(MessageTemplate).filter(MessageTemplate.id == newsletter.template_id).first()
        if template:
            template_name = template.name
    
    creator = db.query(User).filter(User.id == newsletter.created_by_id).first()
    creator_name = f"{creator.first_name} {creator.last_name}".strip() if creator else "Unknown"
    
    return format_newsletter_out(newsletter, template_name, creator_name)


# Get newsletter email logs
@router.get("/get-newsletter-logs/{newsletter_id}", response_model=List[NewsletterEmailLogOut])
def get_newsletter_logs(
    newsletter_id: int,
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get email logs for a newsletter"""
    newsletter = db.query(Newsletter).filter(Newsletter.id == newsletter_id, Newsletter.is_deleted == False).first()
    if not newsletter:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    
    query = db.query(NewsletterEmailLog).filter(NewsletterEmailLog.newsletter_id == newsletter_id)
    
    if status:
        query = query.filter(NewsletterEmailLog.status == status)
    
    logs = query.order_by(desc(NewsletterEmailLog.created_at)).offset(skip).limit(limit).all()
    
    return [NewsletterEmailLogOut(
        id=log.id,
        newsletter_id=log.newsletter_id,
        lead_id=log.lead_id,
        lead_email=log.lead_email,
        lead_name=log.lead_name,
        status=log.status,
        provider_message_id=log.provider_message_id,
        sent_at=log.sent_at,
        delivered_at=log.delivered_at,
        opened_at=log.opened_at,
        clicked_at=log.clicked_at,
        failed_at=log.failed_at,
        bounced_at=log.bounced_at,
        unsubscribed_at=log.unsubscribed_at,
        open_count=log.open_count or 0,
        click_count=log.click_count or 0,
        error_message=log.error_message,
        last_event_at=log.last_event_at,
        created_at=log.created_at
    ) for log in logs]


@router.get("/stats/{newsletter_id}", response_model=NewsletterStatsOut)
def get_newsletter_stats(
    newsletter_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    newsletter = db.query(Newsletter).filter(Newsletter.id == newsletter_id, Newsletter.is_deleted == False).first()
    if not newsletter:
        raise HTTPException(status_code=404, detail="Newsletter not found")

    rows = db.query(
        NewsletterEmailLog.status,
        func.count(NewsletterEmailLog.id)
    ).filter(
        NewsletterEmailLog.newsletter_id == newsletter_id
    ).group_by(NewsletterEmailLog.status).all()

    counts = {status: count for status, count in rows}
    sent = counts.get("sent", 0)
    delivered = counts.get("delivered", 0)
    opened = counts.get("opened", 0)
    clicked = counts.get("clicked", 0)
    failed = counts.get("failed", 0)
    bounced = counts.get("bounced", 0)
    unsubscribed = counts.get("unsubscribed", 0)
    pending = counts.get("queued", 0) + counts.get("pending", 0)

    denominator = sent if sent > 0 else (newsletter.total_recipients or 0)
    delivery_denominator = sent if sent > 0 else 1
    bounce_denominator = sent if sent > 0 else 1

    return NewsletterStatsOut(
        sent=sent,
        delivered=delivered,
        opened=opened,
        clicked=clicked,
        failed=failed,
        bounced=bounced,
        unsubscribed=unsubscribed,
        pending=pending,
        open_rate=round((opened / denominator) * 100, 2) if denominator else 0.0,
        click_rate=round((clicked / denominator) * 100, 2) if denominator else 0.0,
        delivery_rate=round((delivered / delivery_denominator) * 100, 2),
        bounce_rate=round((bounced / bounce_denominator) * 100, 2),
    )


@router.post("/unsubscribe")
def unsubscribe_newsletter(
    payload: NewsletterUnsubscribeRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        token_data = jwt.decode(payload.token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired unsubscribe token")

    lead_id = token_data.get("lead_id")
    newsletter_id = token_data.get("newsletter_id")
    email = token_data.get("email")
    if not lead_id or not newsletter_id or not email:
        raise HTTPException(status_code=400, detail="Invalid unsubscribe token payload")

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    now = ist_now()
    if not lead.is_unsubscribed:
        lead.is_unsubscribed = True
        lead.unsubscribed_at = now

    log = db.query(NewsletterEmailLog).filter(
        NewsletterEmailLog.newsletter_id == newsletter_id,
        NewsletterEmailLog.lead_id == lead_id
    ).order_by(desc(NewsletterEmailLog.id)).first()
    if log:
        _apply_event_status(log, "unsubscribed", now)

    token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    existing_audit = db.query(NewsletterUnsubscribe).filter(
        NewsletterUnsubscribe.newsletter_id == newsletter_id,
        NewsletterUnsubscribe.lead_id == lead_id,
        NewsletterUnsubscribe.token_hash == token_hash
    ).first()
    if not existing_audit:
        audit = NewsletterUnsubscribe(
            newsletter_id=newsletter_id,
            lead_id=lead_id,
            email=email,
            token_hash=token_hash,
            ip=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "")[:500],
            created_at=now,
        )
        db.add(audit)

    db.commit()
    return {"message": "You have been unsubscribed successfully."}


@router.post("/webhooks/provider")
async def provider_webhook(
    payload: NewsletterWebhookPayload,
    request: Request,
    x_webhook_signature: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    webhook_secret = os.getenv("NEWSLETTER_WEBHOOK_SECRET", "").strip()
    if webhook_secret:
        raw = await request.body()
        expected = hmac.new(
            webhook_secret.encode("utf-8"),
            raw,
            hashlib.sha256
        ).hexdigest()
        if not x_webhook_signature or not hmac.compare_digest(x_webhook_signature, expected):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event_map = {
        "delivered": "delivered",
        "open": "opened",
        "opened": "opened",
        "click": "clicked",
        "clicked": "clicked",
        "bounce": "bounced",
        "bounced": "bounced",
        "fail": "failed",
        "failed": "failed",
        "complaint": "complained",
        "unsubscribe": "unsubscribed",
        "unsubscribed": "unsubscribed",
    }

    updated = 0
    missing = 0
    for event in payload.events:
        internal_status = event_map.get((event.event or "").lower())
        if not internal_status:
            continue
        log = db.query(NewsletterEmailLog).filter(
            NewsletterEmailLog.provider_message_id == event.provider_message_id
        ).first()
        if not log:
            missing += 1
            continue
        event_at = event.event_at or ist_now()
        _apply_event_status(log, internal_status, event_at)
        if internal_status in ("failed", "bounced", "complained"):
            log.error_message = event.error_message or log.error_message
        updated += 1

    db.commit()
    return {"updated": updated, "missing": missing}


@router.get("/unsubscribed")
def get_unsubscribed_list(
    newsletter_id: int = Query(...),
    campaign_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(
        NewsletterUnsubscribe.lead_id,
        NewsletterUnsubscribe.email,
        Lead.name,
        NewsletterUnsubscribe.newsletter_id,
        NewsletterUnsubscribe.created_at.label("unsubscribed_at"),
    ).join(
        Lead, Lead.id == NewsletterUnsubscribe.lead_id
    ).filter(
        NewsletterUnsubscribe.newsletter_id == newsletter_id
    )

    if campaign_id is not None:
        query = query.filter(Lead.campaign_id == campaign_id)

    total = query.count()
    rows = query.order_by(desc(NewsletterUnsubscribe.created_at)).offset(skip).limit(limit).all()

    return {
        "unsubscribed": [
            {
                "lead_id": row.lead_id,
                "email": row.email,
                "name": row.name or "",
                "newsletter_id": row.newsletter_id,
                "unsubscribed_at": row.unsubscribed_at,
            }
            for row in rows
        ],
        "total": total
    }


# Get daily email limit status
@router.get("/daily-limit/status", response_model=dict)
def get_daily_limit_status(
    newsletter_id: Optional[int] = Query(None, description="Scope counts to this newsletter's daily cap"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Emails successfully sent today (IST). Pass newsletter_id to use that newsletter's daily_email_limit."""
    today_count = get_daily_email_count(db, newsletter_id=newsletter_id)
    if newsletter_id is not None:
        nl = db.query(Newsletter).filter(Newsletter.id == newsletter_id, Newsletter.is_deleted == False).first()
        limit = (nl.daily_email_limit if nl else None) or 100
    else:
        limit = 100

    return {
        "emails_sent_today": today_count,
        "daily_limit": limit,
        "remaining": max(0, limit - today_count),
        "can_send": today_count < limit,
        "newsletter_id": newsletter_id,
    }


# Get newsletter counts by status
@router.get("/counts", response_model=dict)
def get_newsletter_counts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get count of newsletters by status"""
    all_count = db.query(func.count(Newsletter.id)).scalar() or 0
    draft_count = db.query(func.count(Newsletter.id)).filter(Newsletter.status == "Draft").scalar() or 0
    scheduled_count = db.query(func.count(Newsletter.id)).filter(Newsletter.status == "Scheduled").scalar() or 0
    sending_count = db.query(func.count(Newsletter.id)).filter(Newsletter.status == "Sending").scalar() or 0
    sent_count = db.query(func.count(Newsletter.id)).filter(Newsletter.status == "Sent").scalar() or 0

    return {
        "all": all_count,
        "draft": draft_count,
        "scheduled": scheduled_count,
        "sending": sending_count,
        "sent": sent_count,
    }


def resume_paused_newsletter_sends():
    """Resume newsletters paused on daily cap (status Sending) when quota is available again (IST day)."""
    from database import SessionLocal

    db = SessionLocal()
    try:
        sending_list = db.query(Newsletter).filter(
            Newsletter.status == "Sending",
            Newsletter.is_deleted == False,
        ).all()
        started = 0
        for nl in sending_list:
            can, _used = can_send_email(db, nl.daily_email_limit or 100, nl.id)
            if not can:
                continue
            thread = threading.Thread(target=send_newsletter_emails, args=(nl.id,))
            thread.start()
            started += 1
        if started:
            print(f"✓ Resumed {started} paused newsletter send job(s)")
    except Exception as e:
        print(f"✗ Error resuming paused newsletters: {e}")
    finally:
        db.close()


# Check and send scheduled newsletters (to be called by scheduler)
def check_scheduled_newsletters():
    """Check for scheduled newsletters and send them; also resume Sending paused on daily cap."""
    from database import SessionLocal

    db = SessionLocal()
    try:
        now = ist_now()
        # Get newsletters scheduled to be sent now or in the past
        scheduled_newsletters = db.query(Newsletter).filter(
            Newsletter.status == "Scheduled",
            Newsletter.scheduled_at <= now,
        ).all()

        for newsletter in scheduled_newsletters:
            import threading

            thread = threading.Thread(target=send_newsletter_emails, args=(newsletter.id,))
            thread.start()

        print(f"✓ Checked scheduled newsletters: {len(scheduled_newsletters)} ready to send")
        resume_paused_newsletter_sends()
    except Exception as e:
        print(f"✗ Error checking scheduled newsletters: {e}")
    finally:
        db.close()


# Get available email templates
@router.get("/templates/available")
def get_available_email_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all available email templates for newsletter creation"""
    templates = db.query(MessageTemplate).filter(
        MessageTemplate.template_type == "email",
        MessageTemplate.status == "Active"
    ).all()
    
    return [
        {
            "id": template.id,
            "name": template.name,
            "subject": template.subject,
            "content": template.content[:200] + "..." if len(template.content) > 200 else template.content,
            "editor_mode": template.editor_mode
        }
        for template in templates
    ]


# Get leads for newsletter selection
@router.get("/leads/available")
def get_available_leads(
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all leads available for newsletter selection"""
    query = db.query(Lead).filter(
        Lead.email.isnot(None),
        Lead.email != "",
        Lead.is_deleted == False,
        or_(Lead.is_unsubscribed == False, Lead.is_unsubscribed.is_(None)),
    )
    
    if search:
        query = query.filter(
            or_(
                Lead.name.ilike(f"%{search}%"),
                Lead.email.ilike(f"%{search}%"),
                Lead.phone.ilike(f"%{search}%")
            )
        )
    
    leads = query.order_by(Lead.name).offset(skip).limit(limit).all()
    
    return [
        {
            "id": lead.id,
            "name": lead.name or "Unknown",
            "email": lead.email,
            "phone": lead.phone or "",
            "company": lead.campaign.name if lead.campaign else "",
            "status": lead.status or ""
        }
        for lead in leads
    ]


# Helper function
def format_newsletter_out(newsletter: Newsletter, template_name: Optional[str], creator_name: Optional[str]) -> NewsletterOut:
    """Format Newsletter for output"""
    return NewsletterOut(
        id=newsletter.id,
        subject=newsletter.subject,
        content=newsletter.content,
        content_type=newsletter.content_type,
        template_id=newsletter.template_id,
        recipient_mode=getattr(newsletter, "recipient_mode", None) or "selected_leads",
        campaign_id=getattr(newsletter, "campaign_id", None),
        lead_ids=newsletter.lead_ids,
        status=newsletter.status,
        send_interval=newsletter.send_interval,
        scheduled_at=newsletter.scheduled_at,
        daily_email_limit=newsletter.daily_email_limit,
        send_from_email=getattr(newsletter, "send_from_email", None),
        send_from_name=getattr(newsletter, "send_from_name", None),
        reply_to_email=getattr(newsletter, "reply_to_email", None),
        tracking_campaign_name=getattr(newsletter, "tracking_campaign_name", None),
        per_hour_limit=getattr(newsletter, "per_hour_limit", None) or 50,
        batch_interval_minutes=getattr(newsletter, "batch_interval_minutes", None) or 30,
        include_unsubscribe=getattr(newsletter, "include_unsubscribe", True),
        created_by_id=newsletter.created_by_id,
        total_recipients=newsletter.total_recipients,
        sent_count=newsletter.sent_count,
        failed_count=newsletter.failed_count,
        created_at=newsletter.created_at,
        updated_at=newsletter.updated_at,
        sent_at=newsletter.sent_at,
        template_name=template_name,
        creator_name=creator_name
    )
