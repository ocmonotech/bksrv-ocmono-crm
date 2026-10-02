from sqlalchemy import Column, Integer, String
from database import Base
from sqlalchemy.orm import relationship

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), nullable=False)
    token = Column(String(500), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)