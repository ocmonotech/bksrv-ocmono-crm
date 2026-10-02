from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc
from database import get_db
from models.UsersModel import User
from models.ChatModel import ChatRoom, ChatParticipant, ChatMessage
from models.FileManagerModel import FileRecord
from schemas.ChatSchema import (
    ChatRoomCreate, ChatRoomOut, ChatRoomDetailOut,
    ChatMessageCreate, ChatMessageOut,
    ChatParticipantOut, AddParticipantsRequest, UpdateChatRoomRequest
)
from routers.auth import get_current_user
from routers.FileManager import _resolve_quota_bytes
from typing import List, Optional, Any
from datetime import datetime, timedelta
from utils.datetime_utils import ist_now
import json

router = APIRouter(prefix="/chat", tags=["Chat"])


# Get or create direct chat room between two users
@router.post("/direct-chat/{other_user_id}", response_model=ChatRoomOut)
def get_or_create_direct_chat(
    other_user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get or create a direct chat room between current user and another user"""
    if other_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot create chat with yourself")
    
    # Check if other user exists
    other_user = db.query(User).filter(User.id == other_user_id).first()
    if not other_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if direct chat room already exists
    existing_rooms = db.query(ChatRoom).filter(
        ChatRoom.room_type == "direct"
    ).join(ChatParticipant).filter(
        ChatParticipant.user_id.in_([current_user.id, other_user_id]),
        ChatParticipant.is_active == True
    ).all()
    
    # Find room that has both participants
    for room in existing_rooms:
        participants = [p.user_id for p in room.participants if p.is_active]
        if current_user.id in participants and other_user_id in participants and len(participants) == 2:
            # Get unread count and last message
            unread_count = get_unread_count(room.id, current_user.id, db)
            last_message = get_last_message(room.id, db)
            return format_chat_room_out(room, current_user.id, unread_count, last_message)
    
    # Create new direct chat room
    chat_room = ChatRoom(
        room_type="direct",
        created_by_id=current_user.id
    )
    db.add(chat_room)
    db.flush()
    
    # Add participants
    participant1 = ChatParticipant(chat_room_id=chat_room.id, user_id=current_user.id)
    participant2 = ChatParticipant(chat_room_id=chat_room.id, user_id=other_user_id)
    db.add(participant1)
    db.add(participant2)
    
    db.commit()
    db.refresh(chat_room)
    
    return format_chat_room_out(chat_room, current_user.id, 0, None)


# Create group chat
@router.post("/group-chat", response_model=ChatRoomOut)
def create_group_chat(
    data: ChatRoomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new group chat"""
    if not data.name:
        raise HTTPException(status_code=400, detail="Group name is required")
    
    if not data.participant_ids:
        raise HTTPException(status_code=400, detail="At least one participant is required")
    
    # Verify all users exist
    participant_ids = set(data.participant_ids)
    if current_user.id not in participant_ids:
        participant_ids.add(current_user.id)
    
    users = db.query(User).filter(User.id.in_(participant_ids)).all()
    if len(users) != len(participant_ids):
        raise HTTPException(status_code=404, detail="One or more users not found")
    
    # Create group chat room
    chat_room = ChatRoom(
        name=data.name,
        room_type="group",
        created_by_id=current_user.id
    )
    db.add(chat_room)
    db.flush()
    
    # Add participants
    for user_id in participant_ids:
        participant = ChatParticipant(chat_room_id=chat_room.id, user_id=user_id)
        db.add(participant)
    
    db.commit()
    db.refresh(chat_room)
    
    return format_chat_room_out(chat_room, current_user.id, 0, None)


# Get all chat rooms for current user
@router.get("/rooms", response_model=List[ChatRoomOut])
def get_chat_rooms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all chat rooms for the current user"""
    # Get all chat rooms where user is a participant
    rooms = db.query(ChatRoom).join(ChatParticipant).filter(
        ChatParticipant.user_id == current_user.id,
        ChatParticipant.is_active == True
    ).order_by(desc(ChatRoom.updated_at)).all()
    
    result = []
    for room in rooms:
        unread_count = get_unread_count(room.id, current_user.id, db)
        last_message = get_last_message(room.id, db)
        
        # For direct chats, get the other participant's name
        if room.room_type == "direct":
            other_participant = db.query(ChatParticipant).filter(
                ChatParticipant.chat_room_id == room.id,
                ChatParticipant.user_id != current_user.id,
                ChatParticipant.is_active == True
            ).first()
            if other_participant:
                other_user = db.query(User).filter(User.id == other_participant.user_id).first()
                if other_user:
                    room.name = f"{other_user.first_name} {other_user.last_name}".strip() or other_user.username
        
        result.append(format_chat_room_out(room, current_user.id, unread_count, last_message))
    
    return result


# Get chat room details
@router.get("/rooms/{room_id}", response_model=ChatRoomDetailOut)
def get_chat_room_details(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get detailed information about a chat room"""
    # Verify user is participant
    participant = db.query(ChatParticipant).filter(
        ChatParticipant.chat_room_id == room_id,
        ChatParticipant.user_id == current_user.id,
        ChatParticipant.is_active == True
    ).first()
    
    if not participant:
        raise HTTPException(status_code=403, detail="You are not a participant in this chat room")
    
    room = db.query(ChatRoom).filter(ChatRoom.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Chat room not found")
    
    # Get participants with user details
    participants_data = []
    for p in room.participants:
        if p.is_active:
            user = db.query(User).filter(User.id == p.user_id).first()
            if user:
                participants_data.append(ChatParticipantOut(
                    id=p.id,
                    user_id=p.user_id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    email=user.email,
                    joined_at=p.joined_at,
                    last_read_at=p.last_read_at,
                    is_active=p.is_active
                ))
    
    # Get creator name
    creator = db.query(User).filter(User.id == room.created_by_id).first()
    creator_name = f"{creator.first_name} {creator.last_name}".strip() if creator else "Unknown"
    
    unread_count = get_unread_count(room_id, current_user.id, db)
    
    return ChatRoomDetailOut(
        id=room.id,
        name=room.name,
        room_type=room.room_type,
        created_by_id=room.created_by_id,
        created_by_name=creator_name,
        created_at=room.created_at,
        updated_at=room.updated_at,
        participants=participants_data,
        unread_count=unread_count
    )


# Send message
@router.post("/messages", response_model=ChatMessageOut)
def send_message(
    data: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Send a message to a chat room.

    Supports:
    - message_type=\"text\": plain text message (non-empty after trim).
    - message_type=\"file\": attachments only, with message as JSON string (array/object).
    """
    # Verify user is participant
    participant = db.query(ChatParticipant).filter(
        ChatParticipant.chat_room_id == data.chat_room_id,
        ChatParticipant.user_id == current_user.id,
        ChatParticipant.is_active == True
    ).first()
    
    if not participant:
        raise HTTPException(status_code=403, detail="You are not a participant in this chat room")
    
    # Verify chat room exists
    chat_room = db.query(ChatRoom).filter(ChatRoom.id == data.chat_room_id).first()
    if not chat_room:
        raise HTTPException(status_code=404, detail="Chat room not found")

    msg_type = (data.message_type or "text").lower()
    raw_message: str = data.message or ""

    # Validate and handle by type
    attachments: List[dict] = []
    if msg_type == "text":
        # message must be non-empty after trim
        if not raw_message.strip():
            raise HTTPException(status_code=400, detail="Message text cannot be empty")
    elif msg_type == "file":
        # message is JSON string: array or single object
        if not raw_message.strip():
            raise HTTPException(status_code=400, detail="Attachment payload is required for file messages")
        try:
            parsed: Any = json.loads(raw_message)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid attachment JSON payload")

        if isinstance(parsed, dict):
            attachments = [parsed]
        elif isinstance(parsed, list):
            attachments = parsed
        else:
            raise HTTPException(status_code=400, detail="Attachment payload must be an object or array")

        if not attachments:
            raise HTTPException(status_code=400, detail="At least one attachment is required")

        # Validate each attachment and compute total size
        total_size = 0
        for item in attachments:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail="Each attachment must be an object")
            name = str(item.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="Each attachment must have a name")
            try:
                size_val = int(item.get("size_bytes") or 0)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Attachment size_bytes must be numeric")
            if size_val < 0:
                raise HTTPException(status_code=400, detail="Attachment size_bytes cannot be negative")
            total_size += size_val

        # Enforce storage quota for sender using File Manager logic
        quota_bytes = _resolve_quota_bytes(current_user)
        used_bytes = (
            db.query(func.coalesce(func.sum(FileRecord.size_bytes), 0))
            .filter(FileRecord.user_id == current_user.id)
            .scalar()
            or 0
        )
        if used_bytes + total_size > quota_bytes:
            raise HTTPException(
                status_code=400,
                detail="Storage quota exceeded. Cannot send these attachments.",
            )

        # For DB field, store JSON string exactly as received (normalized)
        raw_message = json.dumps(attachments)
    else:
        # For other types, default to requiring non-empty message
        if not raw_message.strip():
            raise HTTPException(status_code=400, detail="Message text cannot be empty")

    # Create message
    message = ChatMessage(
        chat_room_id=data.chat_room_id,
        sender_id=current_user.id,
        message=raw_message,
        message_type=msg_type,
        file_url=data.file_url,
        file_name=data.file_name,
        file_size=data.file_size,
    )

    db.add(message)

    # If this is a file message, also create File Manager records (same transaction)
    if msg_type == "file" and attachments:
        for item in attachments:
            name = str(item.get("name") or "").strip()
            ext = ""
            if "." in name:
                ext = name.rsplit(".", 1)[-1]
            mime_type = str(item.get("mime_type") or "").strip() or None
            try:
                size_val = int(item.get("size_bytes") or 0)
            except (TypeError, ValueError):
                size_val = 0

            last_modified_at = None
            lm = item.get("last_modified_at")
            if lm:
                s = str(lm).strip()
                try:
                    # Handle possible Z suffix
                    if s.endswith("Z"):
                        s = s[:-1] + "+00:00"
                    last_modified_at = datetime.fromisoformat(s)
                except Exception:
                    last_modified_at = None

            file_rec = FileRecord(
                user_id=current_user.id,
                name=name,
                extension=ext or None,
                mime_type=mime_type,
                size_bytes=size_val,
                category="Chat Attachments",
                tags=None,
                notes=None,
                last_modified_at=last_modified_at,
            )
            db.add(file_rec)

    # Update chat room's updated_at
    chat_room.updated_at = ist_now()

    db.commit()
    db.refresh(message)

    return format_message_out(message, db)


# Get messages for a chat room
@router.get("/rooms/{room_id}/messages", response_model=List[ChatMessageOut])
def get_messages(
    room_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get messages for a chat room"""
    # Verify user is participant
    participant = db.query(ChatParticipant).filter(
        ChatParticipant.chat_room_id == room_id,
        ChatParticipant.user_id == current_user.id,
        ChatParticipant.is_active == True
    ).first()
    
    if not participant:
        raise HTTPException(status_code=403, detail="You are not a participant in this chat room")
    
    # Mark messages as read
    participant.last_read_at = ist_now()
    db.commit()
    
    # Get messages (most recent first, then reverse for chronological order)
    messages = db.query(ChatMessage).filter(
        ChatMessage.chat_room_id == room_id,
        ChatMessage.is_deleted == False
    ).order_by(desc(ChatMessage.created_at)).offset(skip).limit(limit).all()
    
    # Reverse to get chronological order (oldest first)
    messages.reverse()
    
    return [format_message_out(msg, db) for msg in messages]


# Add participants to group chat
@router.post("/rooms/{room_id}/participants", response_model=ChatRoomDetailOut)
def add_participants(
    room_id: int,
    data: AddParticipantsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add participants to a group chat"""
    # Verify chat room is a group
    chat_room = db.query(ChatRoom).filter(ChatRoom.id == room_id).first()
    if not chat_room:
        raise HTTPException(status_code=404, detail="Chat room not found")
    
    if chat_room.room_type != "group":
        raise HTTPException(status_code=400, detail="Can only add participants to group chats")
    
    # Verify current user is participant
    participant = db.query(ChatParticipant).filter(
        ChatParticipant.chat_room_id == room_id,
        ChatParticipant.user_id == current_user.id,
        ChatParticipant.is_active == True
    ).first()
    
    if not participant:
        raise HTTPException(status_code=403, detail="You are not a participant in this chat room")
    
    # Verify all users exist
    existing_participant_ids = {p.user_id for p in chat_room.participants if p.is_active}
    new_user_ids = set(data.user_ids) - existing_participant_ids
    
    if not new_user_ids:
        raise HTTPException(status_code=400, detail="All users are already participants")
    
    users = db.query(User).filter(User.id.in_(new_user_ids)).all()
    if len(users) != len(new_user_ids):
        raise HTTPException(status_code=404, detail="One or more users not found")
    
    # Add participants
    for user_id in new_user_ids:
        # Check if user previously left (reactivate) or create new
        existing = db.query(ChatParticipant).filter(
            ChatParticipant.chat_room_id == room_id,
            ChatParticipant.user_id == user_id
        ).first()
        
        if existing:
            existing.is_active = True
            existing.joined_at = ist_now()
        else:
            participant = ChatParticipant(chat_room_id=room_id, user_id=user_id)
            db.add(participant)
    
    db.commit()
    db.refresh(chat_room)
    
    # Return updated room details
    return get_chat_room_details(room_id, db, current_user)


# Remove participant from group chat
@router.delete("/rooms/{room_id}/participants/{user_id}")
def remove_participant(
    room_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove a participant from a group chat"""
    # Verify chat room is a group
    chat_room = db.query(ChatRoom).filter(ChatRoom.id == room_id).first()
    if not chat_room:
        raise HTTPException(status_code=404, detail="Chat room not found")
    
    if chat_room.room_type != "group":
        raise HTTPException(status_code=400, detail="Can only remove participants from group chats")
    
    # Verify current user is participant (and has permission - creator or removing themselves)
    current_participant = db.query(ChatParticipant).filter(
        ChatParticipant.chat_room_id == room_id,
        ChatParticipant.user_id == current_user.id,
        ChatParticipant.is_active == True
    ).first()
    
    if not current_participant:
        raise HTTPException(status_code=403, detail="You are not a participant in this chat room")
    
    # Only creator can remove others, or user can remove themselves
    if user_id != current_user.id and chat_room.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only group creator can remove other participants")
    
    # Get participant to remove
    participant = db.query(ChatParticipant).filter(
        ChatParticipant.chat_room_id == room_id,
        ChatParticipant.user_id == user_id,
        ChatParticipant.is_active == True
    ).first()
    
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")
    
    # Mark as inactive (soft delete)
    participant.is_active = False
    db.commit()
    
    return {"message": "Participant removed successfully"}


# Edit message
@router.put("/messages/{message_id}", response_model=ChatMessageOut)
def edit_message(
    message_id: int,
    message_text: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Edit a message (only sender can edit)"""
    message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    if message.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own messages")
    
    if message.is_deleted:
        raise HTTPException(status_code=400, detail="Cannot edit deleted messages")
    
    message.message = message_text
    message.is_edited = True
    message.updated_at = ist_now()
    
    db.commit()
    db.refresh(message)
    
    return format_message_out(message, db)


# Delete message (soft delete)
@router.delete("/messages/{message_id}")
def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a message (soft delete - only sender can delete)"""
    message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    if message.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own messages")
    
    message.is_deleted = True
    message.message = "[Message deleted]"
    message.updated_at = ist_now()
    
    db.commit()
    
    return {"message": "Message deleted successfully"}


# Mark messages as read
@router.post("/rooms/{room_id}/mark-read")
def mark_messages_as_read(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark all messages in a chat room as read"""
    participant = db.query(ChatParticipant).filter(
        ChatParticipant.chat_room_id == room_id,
        ChatParticipant.user_id == current_user.id,
        ChatParticipant.is_active == True
    ).first()
    
    if not participant:
        raise HTTPException(status_code=403, detail="You are not a participant in this chat room")
    
    participant.last_read_at = ist_now()
    db.commit()
    
    return {"message": "Messages marked as read"}


# Update group chat name
@router.put("/rooms/{room_id}", response_model=ChatRoomOut)
def update_chat_room(
    room_id: int,
    data: UpdateChatRoomRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update group chat name"""
    chat_room = db.query(ChatRoom).filter(ChatRoom.id == room_id).first()
    if not chat_room:
        raise HTTPException(status_code=404, detail="Chat room not found")
    
    if chat_room.room_type != "group":
        raise HTTPException(status_code=400, detail="Can only update group chat names")
    
    # Verify current user is creator
    if chat_room.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only group creator can update the name")
    
    if data.name:
        chat_room.name = data.name
        db.commit()
        db.refresh(chat_room)
    
    unread_count = get_unread_count(room_id, current_user.id, db)
    last_message = get_last_message(room_id, db)
    return format_chat_room_out(chat_room, current_user.id, unread_count, last_message)


# Get active users (for adding to groups)
@router.get("/users/active", response_model=List[dict])
def get_active_users(
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of active users (excluding current user) for adding to chats"""
    query = db.query(User).filter(User.id != current_user.id)
    
    if search:
        query = query.filter(
            or_(
                User.username.ilike(f"%{search}%"),
                User.first_name.ilike(f"%{search}%"),
                User.last_name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%")
            )
        )
    
    users = query.all()
    
    return [
        {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "full_name": f"{user.first_name} {user.last_name}".strip() or user.username
        }
        for user in users
    ]


# Helper functions
def get_unread_count(room_id: int, user_id: int, db: Session) -> int:
    """Get unread message count for a user in a chat room"""
    participant = db.query(ChatParticipant).filter(
        ChatParticipant.chat_room_id == room_id,
        ChatParticipant.user_id == user_id
    ).first()
    
    if not participant or not participant.last_read_at:
        # Count all messages if never read
        return db.query(ChatMessage).filter(
            ChatMessage.chat_room_id == room_id,
            ChatMessage.sender_id != user_id,
            ChatMessage.is_deleted == False
        ).count()
    
    # Count messages after last_read_at
    return db.query(ChatMessage).filter(
        ChatMessage.chat_room_id == room_id,
        ChatMessage.sender_id != user_id,
        ChatMessage.created_at > participant.last_read_at,
        ChatMessage.is_deleted == False
    ).count()


def get_last_message(room_id: int, db: Session) -> Optional[dict]:
    """Get the last message in a chat room"""
    last_msg = db.query(ChatMessage).filter(
        ChatMessage.chat_room_id == room_id,
        ChatMessage.is_deleted == False
    ).order_by(desc(ChatMessage.created_at)).first()
    
    if not last_msg:
        return None
    
    sender = db.query(User).filter(User.id == last_msg.sender_id).first()
    
    return {
        "id": last_msg.id,
        "message": last_msg.message,
        "sender_name": f"{sender.first_name} {sender.last_name}".strip() if sender else "Unknown",
        "created_at": last_msg.created_at.isoformat() if last_msg.created_at else None
    }


def format_chat_room_out(room: ChatRoom, current_user_id: int, unread_count: int, last_message: Optional[dict]) -> ChatRoomOut:
    """Format ChatRoom for output"""
    return ChatRoomOut(
        id=room.id,
        name=room.name,
        room_type=room.room_type,
        created_by_id=room.created_by_id,
        created_at=room.created_at,
        updated_at=room.updated_at,
        unread_count=unread_count,
        last_message=last_message
    )


def format_message_out(message: ChatMessage, db: Session) -> ChatMessageOut:
    """Format ChatMessage for output"""
    sender = db.query(User).filter(User.id == message.sender_id).first()
    sender_name = f"{sender.first_name} {sender.last_name}".strip() if sender else "Unknown"
    sender_username = sender.username if sender else "unknown"
    
    return ChatMessageOut(
        id=message.id,
        chat_room_id=message.chat_room_id,
        sender_id=message.sender_id,
        sender_name=sender_name,
        sender_username=sender_username,
        message=message.message,
        message_type=message.message_type,
        file_url=message.file_url,
        file_name=message.file_name,
        file_size=message.file_size,
        is_edited=message.is_edited,
        is_deleted=message.is_deleted,
        created_at=message.created_at,
        updated_at=message.updated_at
    )
