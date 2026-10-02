from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Enum as SQLEnum
from sqlalchemy.orm import relationship
from database import Base
import enum
from utils.datetime_utils import ist_now

class ChatRoomType(enum.Enum):
    DIRECT = "direct"  # One-on-one chat
    GROUP = "group"    # Group chat


class ChatRoom(Base):
    __tablename__ = "chat_rooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=True)  # Only for group chats
    room_type = Column(String(20), default="direct")  # direct or group
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by_id])
    participants = relationship("ChatParticipant", back_populates="chat_room", cascade="all, delete-orphan")
    messages = relationship("ChatMessage", back_populates="chat_room", cascade="all, delete-orphan", order_by="ChatMessage.created_at")


class ChatParticipant(Base):
    __tablename__ = "chat_participants"

    id = Column(Integer, primary_key=True, index=True)
    chat_room_id = Column(Integer, ForeignKey("chat_rooms.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    joined_at = Column(DateTime(timezone=True), default=ist_now)
    last_read_at = Column(DateTime(timezone=True), nullable=True)  # For tracking unread messages
    is_active = Column(Boolean, default=True)  # If false, user left the group
    
    # Relationships
    chat_room = relationship("ChatRoom", back_populates="participants")
    user = relationship("User", foreign_keys=[user_id])


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    chat_room_id = Column(Integer, ForeignKey("chat_rooms.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    message_type = Column(String(20), default="text")  # text, image, file, etc.
    file_url = Column(String(500), nullable=True)  # For attachments
    file_name = Column(String(500), nullable=True)  # Original file name
    file_size = Column(Integer, nullable=True)  # File size in bytes
    is_edited = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=ist_now, index=True)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)
    
    # Relationships
    chat_room = relationship("ChatRoom", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id])
