from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from routers import Campaigns, Leads, MessageTemplate, Notes, Tasks, Calls, WhatsApp, Settings, GoogleSheets, LeadImport, auth, BusinessProfile, AppSheets
from database import engine, Base, get_db, SessionLocal
from fastapi import Request, Depends
from routers import project, Attendance, Leave, Notification, ProjectSubTask, AdminCalendar, Assignments, Clients, Admin, ProjectBooking, CampaignBooking, Chat, Newsletter, UserUsage, Todo, UserGroups, Reminders, ReminderGroups, Meetings, FileManager, PunchMachine, AttendanceSettings
from routers.Newsletter import check_scheduled_newsletters
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from routers.auth import get_current_user, get_client_ip, get_location_from_ip
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from routers.Notification import send_email
from models.UsersModel import User
from models.ActivityLogModel import ActivityLog
from starlette.exceptions import HTTPException as StarletteHTTPException
import models.CampaignBookingModel
import models.UserDailyLoginTimeModel
import models.UserUsageModel
import models.AssignmentModel
import models.TaskModel
import models.TodoModel
import models.ReminderModel
import models.ReminderGroupModel
import models.ReminderSnoozeModel
import models.MeetingRoomModel
import models.PunchMachineModel
import models.AttendanceSettingsModel
import models.LeaveModel
import models.BusinessProfileModel
import models.AppSheetModel

# Scheduler must exist before app lifespan; jobs registered before uvicorn serves requests.
scheduler = BackgroundScheduler()


@asynccontextmanager
async def _app_lifespan(app: FastAPI):
    """Start background jobs when ASGI app loads (more reliable than module-level scheduler.start())."""
    if not scheduler.running:
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(lifespan=_app_lifespan)


# Ensure all API errors return JSON (avoids client "Unexpected token 'H'" when proxy returns HTML)
@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    if isinstance(exc.detail, dict):
        body = exc.detail
    else:
        body = {"detail": exc.detail}
    return JSONResponse(content=body, status_code=exc.status_code, media_type="application/json")


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
    body = {"detail": exc.detail}
    return JSONResponse(content=body, status_code=exc.status_code, media_type="application/json")


# Activity logging: only for create / edit / update / delete / patch (not GET)
ACTIVITY_LOG_SKIP_PATHS = {
    "/docs", "/redoc", "/openapi.json", "/favicon.ico",
    "/activity-logs", "/my-activity-logs",
}
ACTIVITY_LOG_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Map path segment to human-readable resource name (singular)
RESOURCE_LABELS = {
    "leads": "lead",
    "campaigns": "campaign",
    "calls": "call",
    "notes": "note",
    "tasks": "task",
    "assignments": "assignment",
    "projects": "project",
    "clients": "client",
    "users": "user",
    "newsletters": "newsletter",
    "message-templates": "message template",
    "settings": "setting",
    "notifications": "notification",
    "attendance": "attendance",
    "leave": "leave",
    "project-booking": "project booking",
    "campaign-booking": "campaign booking",
    "bookings": "booking",
    "slots": "slot",
    "chat": "chat",
    "admin": "admin",
    "user-usage": "user usage",
    "activity-report": "activity report",
    "todos": "todo",
    "user-groups": "user group",
    "reminders": "reminder",
    "meetings": "meeting",
    "punch-machine": "punch machine import",
    "holidays": "holiday",
    "app-sheets": "sheet",
}


def _activity_description(method: str, path: str) -> str:
    """Build human-readable description from method and path."""
    parts = [p for p in path.strip("/").split("/") if p and not p.isdigit()]
    resource = parts[0] if parts else "item"
    resource = RESOURCE_LABELS.get(resource, resource.replace("-", " ").rstrip("s") or resource)
    resource = resource.title()
    if method == "POST":
        return f"Created {resource}"
    if method in ("PUT", "PATCH"):
        return f"Updated {resource}"
    if method == "DELETE":
        return f"Deleted {resource}"
    return f"{method} {path}"


class ActivityLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        method = request.method
        if method not in ACTIVITY_LOG_METHODS:
            return response
        user = getattr(request.state, "user", None)
        if user is None:
            return response
        path = request.url.path
        if any(path.startswith(p) for p in ACTIVITY_LOG_SKIP_PATHS):
            return response
        description = getattr(request.state, "activity_description", None) or _activity_description(method, path)
        activity_type = "create" if method == "POST" else ("update" if method in ("PUT", "PATCH") else "delete")
        ip_address = get_client_ip(request)
        location = get_location_from_ip(ip_address)
        user_agent = request.headers.get("User-Agent", "")[:500]
        db = SessionLocal()
        try:
            log = ActivityLog(
                user_id=user.id,
                username=user.username,
                activity_type=activity_type,
                description=description,
                path=path,
                method=method,
                ip_address=ip_address,
                location=location or None,
                user_agent=user_agent or None,
            )
            db.add(log)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
        return response

# Configure CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "https://crm.ocmono.com", "http://localhost:5175"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create DB Tables
Base.metadata.create_all(bind=engine)

# Include Auth Routes
app.include_router(auth.router)
app.include_router(Campaigns.router)
app.include_router(Leads.router)
app.include_router(Notes.router)
app.include_router(Tasks.router)
app.include_router(MessageTemplate.router)
app.include_router(Calls.router)
app.include_router(WhatsApp.router)
app.include_router(Settings.router)
app.include_router(GoogleSheets.router)
app.include_router(LeadImport.router)

app.include_router(project.router)
app.include_router(Attendance.router)
app.include_router(AttendanceSettings.router)
app.include_router(PunchMachine.router)
app.include_router(Leave.router)
app.include_router(Notification.router)
app.include_router(ProjectSubTask.router)
app.include_router(AdminCalendar.router)
app.include_router(Assignments.router)
app.include_router(Clients.router)
app.include_router(Admin.router)
app.include_router(ProjectBooking.router)
app.include_router(CampaignBooking.router)
app.include_router(Chat.router)
app.include_router(Newsletter.router)
app.include_router(UserUsage.router)
app.include_router(Todo.router)
app.include_router(UserGroups.router)
app.include_router(Reminders.router)
app.include_router(ReminderGroups.router)
app.include_router(Meetings.router)
app.include_router(FileManager.router)
app.include_router(BusinessProfile.router)
app.include_router(AppSheets.router)
app.add_middleware(ActivityLogMiddleware)
app.add_middleware(SessionMiddleware, secret_key="your_secret_key_here")

# Schedule reminders (register before first request; lifespan starts the scheduler)
# scheduler.add_job(send_reminder_to_all_employees, 'cron', hour=10, minute=0, args=["clock_in"])
# scheduler.add_job(send_reminder_to_all_employees, 'cron', hour=10, minute=30, args=["start_timer"])
# scheduler.add_job(send_reminder_to_all_employees, 'cron', hour=19, minute=00, args=["end_timer"])
# scheduler.add_job(send_reminder_to_all_employees, 'cron', hour=19, minute=00, args=["clock_out"])


def send_reminder_email_all(subject, message):
    db = SessionLocal()
    users = db.query(User).filter(User.role == "Employee").all()
    for user in users:
        ok, err = send_email(user.email, subject, message)
        if not ok:
            print(f"Reminder email failed for {user.email}: {err}")
    db.close()



# Clock In & Start Timer Reminder (10:30 AM)
# scheduler.add_job(lambda: send_reminder_email_all(
#     "Start EMS Timer Reminder",
#     "<p>This is your 10:00 AM reminder to clock in and Don't forget to start your task timer.</p>"
# ), 'cron', hour=10, minute=30)

# # Clock In & End Timer Reminder (7:00 PM)
# scheduler.add_job(lambda: send_reminder_email_all(
#     "End EMS Timer Reminder",
#     "<p>Reminder to clock out before ending your day and Please stop your task timer now.</p>"
# ), 'cron', hour=19, minute=0)

# Check scheduled newsletters every minute
scheduler.add_job(check_scheduled_newsletters, 'interval', minutes=1)

# Google Sheets: run due lead syncs every minute (each connection uses sync_frequency / next_sync)
scheduler.add_job(GoogleSheets.run_due_google_sheet_syncs, "interval", minutes=1)
scheduler.add_job(AppSheets.run_due_app_sheet_syncs, "interval", minutes=1)



@app.get("/")
def root():
    return {"message": "Hello World"}
    




