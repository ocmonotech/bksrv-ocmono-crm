from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from database import get_db
from models.NotificationModel import Notification
from models.UsersModel import User
from routers.auth import get_current_user
from utils.notifications import notification_manager, serialize_notification
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from typing import Optional, Tuple
from dotenv import load_dotenv


router = APIRouter()

# See notification according to user
@router.get("/notifications/{user_id}")
def get_notifications(
    user_id: int,
    unread: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Admin" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed")
    query = db.query(Notification).filter(Notification.user_id == user_id)
    if unread:
        query = query.filter(Notification.is_read == False)
    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
    return {
        "notifications": [serialize_notification(n) for n in notifications]
    }

# Mark notification as read
@router.post("/notifications/{notif_id}/read")
def mark_as_read(
    notif_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notif = db.query(Notification).filter(Notification.id == notif_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    if current_user.role != "Admin" and notif.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed")
    notif.is_read = True
    db.commit()
    return {"message": "Marked as read"}

# Send notification manually
@router.get("/test-notification")
def test_notification(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    new_notif = Notification(
        user_id=current_user.id,
        message="Hello!",
        type="general"
    )
    db.add(new_notif)
    db.commit()
    return {"message": "Test notification added"}


# Clear/delete all the notifications
@router.post("/notifications/clear")
def clear_all_notifications(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    db.query(Notification).filter(Notification.user_id == current_user.id).delete()
    db.commit()
    return {"message": "All notifications cleared"}


async def _notifications_ws_handler(websocket: WebSocket, user_id: int):
    await notification_manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        notification_manager.disconnect(user_id, websocket)
    except Exception:
        notification_manager.disconnect(user_id, websocket)


@router.websocket("/ws/notifications/{user_id}")
async def notifications_ws(websocket: WebSocket, user_id: int):
    await _notifications_ws_handler(websocket, user_id)


@router.websocket("/notifications/{user_id}")
async def notifications_ws_legacy(websocket: WebSocket, user_id: int):
    await _notifications_ws_handler(websocket, user_id)


# Sends the daily reminders for log in/out
def send_reminder_to_all_employees(reminder_type: str):
    db: Session = Depends(get_db)
    users = db.query(current_user).filter(current_user.role == "Employee").all()

    messages = {
        "clock_in": "Reminder: Please clock in by 10:00 AM.",
        "start_timer": "Reminder: Start your task timer.",
        "end_timer": "Reminder: Don't forget to stop your timer.",
        "clock_out": "Reminder: Please clock out before 7:00 PM."
    }

    for user in users:
        notif = Notification(user_id=user.id, message=messages[reminder_type])
        db.add(notif)
    db.commit()
    db.close()



load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
# SMTP_FROM allows you to use a different sender email than the login username
# This is required for Brevo - the sender email must be verified in your Brevo account
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)  # Defaults to SMTP_USER if not set
# Port 465 uses implicit TLS (SMTP_SSL). Port 587/2525 use STARTTLS after connect.
_use_ssl_env = os.getenv("SMTP_USE_SSL", "").lower() in ("1", "true", "yes")
SMTP_USE_SSL = _use_ssl_env or SMTP_PORT == 465

def send_email(
    to_email: str,
    subject: str,
    body: str,
    *,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    reply_to: Optional[str] = None,
    campaign_tracking_name: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Send HTML email via SMTP.
    Returns (True, None) on success, or (False, error_message) on failure.
    """
    print(f"Attempting to send email to {to_email} | Subject: {subject}")
    
    # Check if SMTP credentials are configured
    if not SMTP_USER or not SMTP_PASS:
        cfg_err = "SMTP_USER and SMTP_PASS are not set in environment (.env). Email cannot be sent."
        print("⚠️  Email not sent: SMTP credentials not configured in .env file")
        print("   Please set SMTP_USER and SMTP_PASS in your .env file")
        return False, cfg_err
    
    # Per-message overrides (Brevo-style); envelope sender must stay verified (SMTP_FROM)
    envelope_from = SMTP_FROM or SMTP_USER
    display_from_email = from_email or envelope_from
    try:
        msg = MIMEMultipart()
        if from_name and display_from_email:
            msg["From"] = formataddr((from_name, display_from_email))
        else:
            msg["From"] = display_from_email
        msg["To"] = to_email
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to
        if campaign_tracking_name:
            msg["X-Campaign-Name"] = campaign_tracking_name
        msg.attach(MIMEText(body, "html"))

        if SMTP_USE_SSL:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(envelope_from, to_email, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(envelope_from, to_email, msg.as_string())

        print("✓ Email sent successfully.")
        return True, None

    except smtplib.SMTPAuthenticationError as e:
        hints = (
            "Check .env: SMTP_USER and SMTP_PASS must match your provider. "
            "Gmail: use an App Password (2FA on), not your normal password. "
            "Brevo/Sendinblue: SMTP_PASS is the SMTP key from SMTP & API, not your login password. "
            "If you use port 465, set SMTP_PORT=465 (implicit SSL) or SMTP_USE_SSL=true."
        )
        err = f"SMTP authentication failed (535): {e}. {hints}"
        print(f"✗ Email authentication failed: {e}")
        print("   Please check your SMTP_USER and SMTP_PASS in .env file")
        print("   For Gmail, you may need to use an App Password instead of your regular password")
        print("   Visit: https://support.google.com/accounts/answer/185833")
        return False, err
    except smtplib.SMTPException as e:
        error_msg = str(e)
        print(f"✗ SMTP error occurred: {error_msg}")
        
        # Check for Brevo-specific sender validation errors
        if "smtp-brevo.com" in error_msg.lower() or "brevo" in error_msg.lower():
            print("\n⚠️  BREVO SENDER VALIDATION ERROR:")
            print("   The sender email address must be verified in your Brevo account.")
            print("   Even if your domain is authenticated, the sender email itself must be verified.")
            print("\n   Solutions:")
            print("   1. Go to Brevo Dashboard → Senders & IP → Senders")
            print("   2. Add and verify the sender email address you want to use")
            print("   3. Set SMTP_FROM in your .env file to the verified sender email")
            print("      Example: SMTP_FROM=noreply@yourdomain.com")
            print("   4. Make sure SMTP_FROM uses your verified domain, not @smtp-brevo.com")
            print("\n   Note: SMTP_USER should be your Brevo SMTP login (usually your account email)")
            print("         SMTP_FROM should be the verified sender email address")
        
        # Check for general sender validation errors
        if "sender" in error_msg.lower() and ("not valid" in error_msg.lower() or "not verified" in error_msg.lower() or "validate" in error_msg.lower()):
            print("\n⚠️  SENDER VALIDATION ERROR:")
            print("   The sender email address is not valid or not verified.")
            print("   Please verify the sender email in your email service provider's dashboard.")
            if "brevo" in SMTP_HOST.lower() or "sendinblue" in SMTP_HOST.lower():
                print("   For Brevo: Dashboard → Senders & IP → Senders → Add and verify sender")
        
        return False, f"SMTP error: {error_msg}"
    except Exception as e:
        error_msg = str(e)
        print(f"✗ Email send failed: {error_msg}")
        print(f"   Error type: {type(e).__name__}")
        
        # Check error message for Brevo-specific issues
        if "smtp-brevo.com" in error_msg.lower() or ("sender" in error_msg.lower() and "not valid" in error_msg.lower()):
            print("\n⚠️  BREVO SENDER VALIDATION ISSUE DETECTED:")
            print("   Please verify your sender email in Brevo Dashboard.")
            print("   Set SMTP_FROM in .env to your verified sender email address.")
        
        return False, f"{type(e).__name__}: {error_msg}"



@router.get("/send-test-email")
def send_test_email():
    ok, err = send_email("ocmono.design@gmail.com", "Test Email", "<h3>This is a test</h3>")
    body: dict = {"ok": ok, "error": err}
    if not ok:
        body["smtp"] = {"host": SMTP_HOST, "port": SMTP_PORT, "use_ssl": SMTP_USE_SSL}
    return body
