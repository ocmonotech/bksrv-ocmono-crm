from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ChatRoomCreate(BaseModel):
    name: Optional[str] = None  # Required for group chats
    room_type: str = "direct"  # direct or group
    participant_ids: List[int] = []  # User IDs to add (for group chat)


class ChatRoomOut(BaseModel):
    id: int
    name: Optional[str]
    room_type: str
    created_by_id: int
    created_at: datetime
    updated_at: datetime
    unread_count: Optional[int] = 0
    last_message: Optional[dict] = None
    
    class Config:
        from_attributes = True


class ChatParticipantOut(BaseModel):
    id: int
    user_id: int
    username: str
    first_name: str
    last_name: str
    email: str
    joined_at: datetime
    last_read_at: Optional[datetime]
    is_active: bool
    
    class Config:
        from_attributes = True


class ChatMessageCreate(BaseModel):
    chat_room_id: int
    # For message_type="text": required, non-empty after trim.
    # For message_type="file": JSON string (array/object) describing attachments.
    message: Optional[str] = None
    message_type: str = "text"
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None


class ChatMessageOut(BaseModel):
    id: int
    chat_room_id: int
    sender_id: int
    sender_name: str
    sender_username: str
    message: str
    message_type: str
    file_url: Optional[str]
    file_name: Optional[str]
    file_size: Optional[int]
    is_edited: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ChatRoomDetailOut(BaseModel):
    id: int
    name: Optional[str]
    room_type: str
    created_by_id: int
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    participants: List[ChatParticipantOut]
    unread_count: int = 0
    
    class Config:
        from_attributes = True


class AddParticipantsRequest(BaseModel):
    user_ids: List[int]


class UpdateChatRoomRequest(BaseModel):
    name: Optional[str] = None
