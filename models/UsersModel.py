from sqlalchemy import Column, Integer, String, Boolean, DateTime
from database import Base
from sqlalchemy.orm import relationship
from models.AssignmentModel import assignment_user_association


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    email = Column(String(50), unique=True, index=True)
    first_name = Column(String(50))
    last_name = Column(String(50))
    role = Column(String(50))
    hashed_password = Column(String(10000))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    attendances = relationship("Attendance", back_populates="user")
    assigned_assignments = relationship("Assignment", secondary=assignment_user_association, back_populates="assigned_users")
    assigned_tasks = relationship("Task", secondary="task_user_association", back_populates="assigned_users")
    assigned_todos = relationship("Todo", secondary="todo_user_association", back_populates="assigned_users")
    assigned_reminders = relationship("Reminder", secondary="reminder_user_association", back_populates="assigned_users")
    assigned_reminder_groups = relationship(
        "ReminderGroup",
        secondary="reminder_group_user_association",
        back_populates="assigned_users",
    )
    chat_participations = relationship("ChatParticipant", back_populates="user", foreign_keys="ChatParticipant.user_id")
    sent_messages = relationship("ChatMessage", back_populates="sender", foreign_keys="ChatMessage.sender_id")
    created_chat_rooms = relationship("ChatRoom", back_populates="creator", foreign_keys="ChatRoom.created_by_id")