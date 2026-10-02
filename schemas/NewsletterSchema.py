from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime


class NewsletterCreate(BaseModel):
    subject: str
    content: str
    content_type: str = "plain"  # plain, html, rich
    template_id: Optional[int] = None
    recipient_mode: Literal["campaign", "selected_leads"] = "selected_leads"
    campaign_id: Optional[int] = None
    lead_ids: List[int] = Field(default_factory=list)
    status: str = "Draft"  # Draft, Scheduled, Sending, Sent
    send_interval: str = "once"  # once, daily, weekly, monthly
    scheduled_at: Optional[datetime] = None
    daily_email_limit: int = 100
    send_from_email: Optional[str] = None
    send_from_name: Optional[str] = None
    reply_to_email: Optional[str] = None
    tracking_campaign_name: Optional[str] = None
    per_hour_limit: int = 50
    batch_interval_minutes: int = 30
    include_unsubscribe: bool = True
    send_now: bool = True


class NewsletterUpdate(BaseModel):
    subject: Optional[str] = None
    content: Optional[str] = None
    content_type: Optional[str] = None
    template_id: Optional[int] = None
    recipient_mode: Optional[Literal["campaign", "selected_leads"]] = None
    campaign_id: Optional[int] = None
    lead_ids: Optional[List[int]] = None
    status: Optional[str] = None
    send_interval: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    daily_email_limit: Optional[int] = None
    send_from_email: Optional[str] = None
    send_from_name: Optional[str] = None
    reply_to_email: Optional[str] = None
    tracking_campaign_name: Optional[str] = None
    per_hour_limit: Optional[int] = None
    batch_interval_minutes: Optional[int] = None
    include_unsubscribe: Optional[bool] = None


class NewsletterOut(BaseModel):
    id: int
    subject: str
    content: str
    content_type: str
    template_id: Optional[int]
    recipient_mode: str
    campaign_id: Optional[int]
    lead_ids: List[int]
    status: str  # Draft, Scheduled, Sending, Sent
    send_interval: str
    scheduled_at: Optional[datetime]
    daily_email_limit: int
    send_from_email: Optional[str] = None
    send_from_name: Optional[str] = None
    reply_to_email: Optional[str] = None
    tracking_campaign_name: Optional[str] = None
    per_hour_limit: int = 50
    batch_interval_minutes: int = 30
    include_unsubscribe: bool = True
    created_by_id: int
    total_recipients: int
    sent_count: int
    failed_count: int
    created_at: datetime
    updated_at: datetime
    sent_at: Optional[datetime]
    template_name: Optional[str] = None
    creator_name: Optional[str] = None
    
    class Config:
        from_attributes = True


class NewsletterPreviewRequest(BaseModel):
    subject: str
    content: str
    content_type: str = "plain"
    lead_id: int  # Preview with a specific lead's data


class NewsletterPreviewResponse(BaseModel):
    subject: str
    content: str
    lead_name: str
    lead_email: str


class NewsletterEmailLogOut(BaseModel):
    id: int
    newsletter_id: int
    lead_id: int
    lead_email: str
    lead_name: Optional[str]
    status: str
    provider_message_id: Optional[str] = None
    sent_at: Optional[datetime]
    delivered_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    clicked_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    bounced_at: Optional[datetime] = None
    unsubscribed_at: Optional[datetime] = None
    open_count: int = 0
    click_count: int = 0
    error_message: Optional[str]
    last_event_at: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class DailyEmailLimitOut(BaseModel):
    id: int
    date: datetime
    emails_sent: int
    updated_at: datetime
    
    class Config:
        from_attributes = True


class NewsletterStatsOut(BaseModel):
    sent: int = 0
    delivered: int = 0
    opened: int = 0
    clicked: int = 0
    failed: int = 0
    bounced: int = 0
    unsubscribed: int = 0
    pending: int = 0
    open_rate: float = 0.0
    click_rate: float = 0.0
    delivery_rate: float = 0.0
    bounce_rate: float = 0.0


class NewsletterUnsubscribeRequest(BaseModel):
    token: str


class NewsletterWebhookEvent(BaseModel):
    event: str
    provider_message_id: str
    event_at: Optional[datetime] = None
    error_message: Optional[str] = None


class NewsletterWebhookPayload(BaseModel):
    events: List[NewsletterWebhookEvent]
