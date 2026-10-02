"""Automatic welcome email when a new lead is created (any source: API, sheet sync, import)."""

from __future__ import annotations

import re
import traceback
from sqlalchemy import func

from database import SessionLocal
from models.LeadsModel import Lead
from models.MessageTemplateModel import MessageTemplate
from models.SettingsModel import Settings
from routers.Notification import send_email
from utils.datetime_utils import ist_now


def replace_template_variables(content: str, lead_data: dict) -> str:
    """Replace template variables with actual lead data."""
    replacements = {
        "{{name}}": lead_data.get("name", ""),
        "{{email}}": lead_data.get("email", ""),
        "{{phone}}": lead_data.get("phone", ""),
        "{{campaign}}": lead_data.get("campaign_name", ""),
        "{{source}}": lead_data.get("source", ""),
        "{{status}}": lead_data.get("status", ""),
        "{{date}}": ist_now().strftime("%Y-%m-%d"),
        "{{time}}": ist_now().strftime("%H:%M:%S"),
    }

    result = content
    for var, value in replacements.items():
        result = result.replace(var, str(value))

    def replace_var(match):
        var_name = match.group(1).lower()
        return str(lead_data.get(var_name, ""))

    result = re.sub(r"\{\{(\w+)\}\}", replace_var, result)
    return result


def send_welcome_email_to_lead(lead_id: int) -> bool:
    """Send welcome email to lead using the configured template and settings."""
    db = SessionLocal()
    try:
        auto_email_setting = db.query(Settings).filter(Settings.key == "auto_welcome_email_enabled").first()
        if auto_email_setting and auto_email_setting.value and auto_email_setting.value.lower() == "false":
            print("ℹ️  Automatic welcome emails are disabled. Skipping email.")
            return False

        lead = db.query(Lead).filter(Lead.id == lead_id, Lead.is_deleted == False).first()
        if not lead:
            print(f"⚠️  Lead {lead_id} not found. Skipping email.")
            return False

        if not (lead.email or "").strip():
            print(f"ℹ️  Lead {lead_id} has no email. Skipping welcome email.")
            return False

        setting = db.query(Settings).filter(Settings.key == "welcome_email_template_id").first()
        if not setting or not setting.value:
            print("⚠️  No welcome email template configured. Skipping email.")
            print("   Set a template using: POST /settings/set-welcome-email-template/{template_id}")
            return False

        template_id = int(setting.value)
        template = (
            db.query(MessageTemplate)
            .filter(
                MessageTemplate.id == template_id,
                MessageTemplate.template_type == "email",
                func.lower(func.trim(MessageTemplate.status)) == "active",
            )
            .first()
        )

        if not template:
            print(f"⚠️  Template {template_id} not found or not active. Skipping email.")
            return False

        lead_data = {
            "name": lead.name,
            "email": lead.email,
            "phone": lead.phone or "",
            "status": lead.status or "",
            "date": ist_now().strftime("%Y-%m-%d"),
            "time": ist_now().strftime("%H:%M:%S"),
        }

        subject = replace_template_variables(template.subject or "Welcome", lead_data)
        content = replace_template_variables(template.content, lead_data)

        success, _ = send_email(lead.email.strip(), subject, content)

        template.usage_count += 1
        if success:
            template.success_count += 1
        if template.usage_count > 0:
            template.success_rate = (template.success_count / template.usage_count) * 100
        db.commit()

        if not success:
            print(f"⚠️  Welcome email failed for lead {lead_id} ({lead.email}), but lead was created successfully.")

        return success

    except Exception as e:
        print(f"✗ Error sending welcome email: {e}")
        print(f"   Lead {lead_id} was created successfully, but email could not be sent.")
        traceback.print_exc()
        return False
    finally:
        db.close()
