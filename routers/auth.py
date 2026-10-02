from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.UsersModel import User
from models.ActivityLogModel import ActivityLog
from security import get_password_hash, verify_password
from datetime import timedelta, timezone as dt_tz
from models.AttendanceModel import Attendance
from models.UserDailyLoginTimeModel import UserDailyLoginTime
from sqlalchemy import and_, desc
from utils.datetime_utils import IST, ist_now
from itsdangerous import URLSafeTimedSerializer
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
from typing import Optional

router = APIRouter()

SECRET_KEY = "ocmono@2025-secret-key"
serializer = URLSafeTimedSerializer(SECRET_KEY)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days (for desktop app 5-min reports)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = ist_now() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def _auth_error(detail: str, code: str = "invalid_credentials"):
    """Raise 401 with JSON body so API clients always get parseable JSON."""
    raise HTTPException(status_code=401, detail={"detail": detail, "code": code})


def get_bearer_token(request: Request) -> str:
    """Extract JWT from Authorization: Bearer <token> or X-Access-Token (for desktop apps)."""
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        return auth[7:].strip()
    token = request.headers.get("X-Access-Token")
    if token:
        return token.strip()
    _auth_error("Missing or invalid authorization. Use Authorization: Bearer <token> or X-Access-Token header.", "missing_token")


# Pydantic models for request bodies
class UserRegister(BaseModel):
    username: str
    email: str
    first_name: str
    last_name: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

# Helper function to get current user (sets request.state.user for activity logging middleware)
# Uses get_bearer_token so desktop app can send either Authorization: Bearer <token> or X-Access-Token
def get_current_user(
    request: Request,
    token: str = Depends(get_bearer_token),
    db: Session = Depends(get_db),
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            _auth_error("Invalid credentials", "invalid_token")
    except ExpiredSignatureError:
        _auth_error("Token expired. Please log out and log in again.", "token_expired")
    except JWTError:
            _auth_error("Invalid credentials", "invalid_token")

    user = db.query(User).filter(User.username == username, User.is_deleted == False).first()
    if user is None:
        _auth_error("User not found. Please log out and log in again.", "user_not_found")
    # Set on request for activity logging middleware
    request.state.user = user
    return user


def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Require Admin role. Use for hard-delete and other admin-only operations."""
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user


# Register POST
@router.post("/register")
def register_user(
    request: Request,
    user_data: UserRegister,
    db: Session = Depends(get_db),
):
    existing_user = db.query(User).filter((User.username == user_data.username) | (User.email == user_data.email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username or email already registered")

    user = User(
        username=user_data.username,
        email=user_data.email,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        role="Employee",  # Default to Employee
        hashed_password=get_password_hash(user_data.password)
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return {
        "message": "User registered successfully",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role
        }
    }


# Helper function to get client IP address
def get_client_ip(request: Request) -> str:
    """Get client IP address from request"""
    # Check for forwarded IP (when behind proxy/load balancer)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # X-Forwarded-For can contain multiple IPs, take the first one
        return forwarded.split(",")[0].strip()
    
    # Check for real IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fallback to direct client IP
    if request.client:
        return request.client.host
    
    return "unknown"


# Helper function to get user agent
def get_user_agent(request: Request) -> str:
    """Get user agent from request"""
    return request.headers.get("User-Agent", "unknown")[:500]  # Limit to 500 chars


def get_location_from_ip(ip_address: str) -> str:
    """Resolve location (City, Country) from IP using free ip-api.com (no key, 45 req/min)."""
    if not ip_address or ip_address in ("unknown", "127.0.0.1", "localhost"):
        return "Local"
    try:
        import urllib.request
        url = f"http://ip-api.com/json/{ip_address}?fields=city,country,regionName"
        req = urllib.request.Request(url, headers={"User-Agent": "OcmonoCRM/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            import json
            data = json.loads(resp.read().decode())
            city = data.get("city") or ""
            region = data.get("regionName") or ""
            country = data.get("country") or ""
            parts = [p for p in (city, region, country) if p]
            return ", ".join(parts)[:255] if parts else "Unknown"
    except Exception:
        return "Unknown"


# Login POST
@router.post("/login")
def login_user(
    login_data: UserLogin,
    request: Request,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == login_data.username).first()
    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Get IP address and user agent
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    # Mark attendance for employee login
    if user.role == "Employee":
        today = ist_now().date()
        existing = db.query(Attendance).filter(
            Attendance.username == user.username,
            Attendance.date == today
        ).first()

        if not existing:
            now_ist = ist_now()
            new_attendance = Attendance(
                username=user.username,
                login_time=now_ist,
                date=today
            )
            db.add(new_attendance)

    # Log activity with IP, location, and description
    location = get_location_from_ip(ip_address)
    activity_log = ActivityLog(
        user_id=user.id,
        username=user.username,
        activity_type="login",
        description="Logged in",
        ip_address=ip_address,
        location=location,
        user_agent=user_agent
    )
    db.add(activity_log)
    db.commit()

    # Create JWT token
    token_data = {
        "sub": user.username,
        "role": user.role,
        "user_id": user.id
    }
    access_token = create_access_token(token_data, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

    return {
        "access_token": access_token,
        "token": access_token,  # alias for desktop/apps that read data.token
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role
        },
        "redirect": (
            "/dashboard/analytics" if user.role == "Admin"
            else "/client-dashboard" if user.role == "Client"
            else "/employee-dashboard"
        )
    }


# Logout
@router.post("/logout")
def logout_user(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    username = request.session.get("username") or current_user.username
    user_id = current_user.id
    
    if username:
        today = ist_now().date()
        attendance = db.query(Attendance).filter(
            and_( 
                Attendance.username == username,
                Attendance.date == today
            )
        ).first()
        if attendance:
            # Always keep the latest logout time for the day.
            now_ist = ist_now()
            attendance.logout_time = now_ist

    # Log logout activity with IP, location, and description
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    location = get_location_from_ip(ip_address)
    activity_log = ActivityLog(
        user_id=user_id,
        username=username,
        activity_type="logout",
        description="Logged out",
        ip_address=ip_address,
        location=location,
        user_agent=user_agent
    )
    db.add(activity_log)

    # Update daily login time: find last login and add this session duration
    last_login = (
        db.query(ActivityLog)
        .filter(ActivityLog.user_id == user_id, ActivityLog.activity_type == "login")
        .order_by(desc(ActivityLog.created_at))
        .limit(1)
        .first()
    )
    if last_login and last_login.created_at:
        logout_now = ist_now()
        login_dt = last_login.created_at
        if login_dt.tzinfo is None:
            login_dt = login_dt.replace(tzinfo=dt_tz.utc)
        login_dt_india = login_dt.astimezone(IST)
        login_date = login_dt_india.date()
        duration_seconds = int((logout_now - login_dt_india).total_seconds())
        if duration_seconds > 0:
            row = (
                db.query(UserDailyLoginTime)
                .filter(
                    UserDailyLoginTime.user_id == user_id,
                    UserDailyLoginTime.date == login_date,
                )
                .first()
            )
            if row:
                row.total_seconds_logged_in += duration_seconds
            else:
                db.add(
                    UserDailyLoginTime(
                        user_id=user_id,
                        date=login_date,
                        total_seconds_logged_in=duration_seconds,
                    )
                )

    db.commit()

    request.session.clear()
    return {"message": "Logout successful"}


# Get current user info
@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "role": current_user.role
    }


# Reset Password code

conf = ConnectionConfig(
    MAIL_USERNAME="no.reply.ocmono@gmail.com",
    MAIL_PASSWORD="ovaa jsqd wxvi ydlh",
    MAIL_FROM="ocmono.design@gmail.com",
    MAIL_PORT=587,
    MAIL_SERVER="smtp.gmail.com",
    MAIL_STARTTLS=True,                         
    MAIL_SSL_TLS=False,   
    USE_CREDENTIALS=True
)

@router.post("/forgot-password")
async def forgot_password(request: Request, forgot_data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == forgot_data.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User with this email not found")

    token = serializer.dumps(user.username, salt="reset-password")
    reset_url = f"http://crm.ocmono.com/reset-password?token={token}"

    message = MessageSchema(
        subject="Reset your EMS Password",
        recipients=[user.email],
        body=f"<p>Click the link to reset your password:</p><a href='{reset_url}'>{reset_url}</a>",
        subtype="html"
    )

    fm = FastMail(conf)
    await fm.send_message(message)
    
    return {"message": "Password reset link sent to your email"}


# Verify reset token
@router.get("/verify-reset-token")
def verify_reset_token(token: str):
    try:
        username = serializer.loads(token, salt="reset-password", max_age=3600)  # 1 hour expiry
        return {"valid": True, "username": username}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

@router.post("/reset-password")
def reset_password_submit(
    reset_data: ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    try:
        username = serializer.loads(reset_data.token, salt="reset-password", max_age=3600)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user = db.query(User).filter(User.username == username, User.is_deleted == False).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = get_password_hash(reset_data.new_password)
    db.commit()
    
    return {"message": "Password reset successfully"}


# Get activity logs
@router.get("/activity-logs")
def get_activity_logs(
    user_id: Optional[int] = None,
    activity_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get activity logs (Admin can see all, others see only their own)"""
    from schemas.ActivityLogSchema import ActivityLogOut
    from sqlalchemy import desc
    from typing import Optional
    
    query = db.query(ActivityLog)
    
    # Non-admin users can only see their own logs
    if current_user.role != "Admin":
        query = query.filter(ActivityLog.user_id == current_user.id)
    elif user_id:
        query = query.filter(ActivityLog.user_id == user_id)
    
    if activity_type:
        query = query.filter(ActivityLog.activity_type == activity_type)
    
    logs = query.order_by(desc(ActivityLog.created_at)).offset(skip).limit(limit).all()
    
    return [ActivityLogOut(
        id=log.id,
        user_id=log.user_id,
        username=log.username,
        activity_type=log.activity_type,
        description=log.description,
        path=log.path,
        method=log.method,
        ip_address=log.ip_address,
        location=log.location,
        user_agent=log.user_agent,
        created_at=log.created_at
    ) for log in logs]


# Get my activity logs
@router.get("/my-activity-logs")
def get_my_activity_logs(
    activity_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get current user's activity logs"""
    from schemas.ActivityLogSchema import ActivityLogOut
    from sqlalchemy import desc
    from typing import Optional
    
    query = db.query(ActivityLog).filter(ActivityLog.user_id == current_user.id)
    
    if activity_type:
        query = query.filter(ActivityLog.activity_type == activity_type)
    
    logs = query.order_by(desc(ActivityLog.created_at)).offset(skip).limit(limit).all()
    
    return [ActivityLogOut(
        id=log.id,
        user_id=log.user_id,
        username=log.username,
        activity_type=log.activity_type,
        description=log.description,
        path=log.path,
        method=log.method,
        ip_address=log.ip_address,
        location=log.location,
        user_agent=log.user_agent,
        created_at=log.created_at
    ) for log in logs]

# Get daily login time (all users, Admin only) — per user, per day, for all days
@router.get("/user-daily-login-time")
def get_user_daily_login_time(
    user_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    skip: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get daily login time per user. Admin only. Optional filters: user_id, date_from (YYYY-MM-DD), date_to (YYYY-MM-DD)."""
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Admin only")
    query = db.query(UserDailyLoginTime, User.username).join(User, User.id == UserDailyLoginTime.user_id)
    if user_id is not None:
        query = query.filter(UserDailyLoginTime.user_id == user_id)
    if date_from:
        query = query.filter(UserDailyLoginTime.date >= date_from)
    if date_to:
        query = query.filter(UserDailyLoginTime.date <= date_to)
    rows = query.order_by(UserDailyLoginTime.date.desc(), UserDailyLoginTime.user_id).offset(skip).limit(limit).all()
    out = []
    for row, username in rows:
        s = row.total_seconds_logged_in
        h, r = divmod(s, 3600)
        m, r = divmod(r, 60)
        out.append({
            "user_id": row.user_id,
            "username": username,
            "date": row.date.isoformat() if hasattr(row.date, "isoformat") else str(row.date),
            "total_seconds_logged_in": row.total_seconds_logged_in,
            "total_minutes": round(row.total_seconds_logged_in / 60, 1),
            "formatted": f"{int(h)}h {int(m)}m",
        })
    return out


# Get my daily login time — current user, all days
@router.get("/my-daily-login-time")
def get_my_daily_login_time(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    skip: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current user's daily login time (how long logged in each day)."""
    query = db.query(UserDailyLoginTime).filter(UserDailyLoginTime.user_id == current_user.id)
    if date_from:
        query = query.filter(UserDailyLoginTime.date >= date_from)
    if date_to:
        query = query.filter(UserDailyLoginTime.date <= date_to)
    rows = query.order_by(UserDailyLoginTime.date.desc()).offset(skip).limit(limit).all()
    out = []
    for row in rows:
        s = row.total_seconds_logged_in
        h, r = divmod(s, 3600)
        m, r = divmod(r, 60)
        out.append({
            "user_id": row.user_id,
            "username": current_user.username,
            "date": row.date.isoformat() if hasattr(row.date, "isoformat") else str(row.date),
            "total_seconds_logged_in": row.total_seconds_logged_in,
            "total_minutes": round(row.total_seconds_logged_in / 60, 1),
            "formatted": f"{int(h)}h {int(m)}m",
        })
    return out


# Get all users
@router.get("/users-list")
def get_all_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [{
    "id": user.id, 
    "username": user.username,
    "email": user.email,
    "first_name": user.first_name, 
    "last_name": user.last_name,
    "role": user.role
    } for user in users]