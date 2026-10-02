from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now


class Newsletter(Base):
    __tablename__ = "newsletters"

    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    content_type = Column(String(20), default="plain")  # plain, html, rich
    template_id = Column(Integer, ForeignKey("message_templates.id"), nullable=True)
    lead_ids = Column(JSON, nullable=False)  # Array of lead IDs
    status = Column(String(20))  # Draft, Scheduled, Sending, Sent
    send_interval = Column(String(20), default="once")  # once, daily, weekly, monthly
    scheduled_at = Column(DateTime, nullable=True)  # When to send (for scheduled)
    daily_email_limit = Column(Integer, default=100)  # Max emails per day
    recipient_mode = Column(String(30), default="selected_leads")  # campaign | selected_leads
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    send_from_email = Column(String(255), nullable=True)
    send_from_name = Column(String(255), nullable=True)
    reply_to_email = Column(String(255), nullable=True)
    tracking_campaign_name = Column(String(255), nullable=True)  # Brevo / provider campaign name
    per_hour_limit = Column(Integer, default=50)
    batch_interval_minutes = Column(Integer, default=30)
    include_unsubscribe = Column(Boolean, default=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    total_recipients = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)
    sent_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    template = relationship("MessageTemplate", foreign_keys=[template_id])
    creator = relationship("User", foreign_keys=[created_by_id])
    campaign = relationship("Campaign", foreign_keys=[campaign_id])
    email_logs = relationship("NewsletterEmailLog", back_populates="newsletter", cascade="all, delete-orphan")


class NewsletterEmailLog(Base):
    __tablename__ = "newsletter_email_logs"

    id = Column(Integer, primary_key=True, index=True)
    newsletter_id = Column(Integer, ForeignKey("newsletters.id"), nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    lead_email = Column(String(200), nullable=False)
    lead_name = Column(String(200), nullable=True)
    provider_message_id = Column(String(255), nullable=True, unique=True, index=True)
    status = Column(String(20), default="queued")  # queued, sent, delivered, opened, clicked, failed, bounced, complained, unsubscribed
    sent_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    opened_at = Column(DateTime, nullable=True)
    clicked_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    bounced_at = Column(DateTime, nullable=True)
    unsubscribed_at = Column(DateTime, nullable=True)
    open_count = Column(Integer, default=0)
    click_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    last_event_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ist_now, index=True)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)
    
    # Relationships
    newsletter = relationship("Newsletter", back_populates="email_logs")
    lead = relationship("Lead", foreign_keys=[lead_id])


class NewsletterUnsubscribe(Base):
    __tablename__ = "newsletter_unsubscribes"

    id = Column(Integer, primary_key=True, index=True)
    newsletter_id = Column(Integer, ForeignKey("newsletters.id"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    email = Column(String(255), nullable=False)
    token_hash = Column(String(255), nullable=True)
    ip = Column(String(100), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ist_now, index=True)

    newsletter = relationship("Newsletter", foreign_keys=[newsletter_id])
    lead = relationship("Lead", foreign_keys=[lead_id])


class DailyEmailLimit(Base):
    __tablename__ = "daily_email_limits"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False, unique=True, index=True)  # Date only (YYYY-MM-DD)
    emails_sent = Column(Integer, default=0)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)
