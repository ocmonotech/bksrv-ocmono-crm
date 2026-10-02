from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text
from database import Base
from sqlalchemy.orm import relationship
from utils.datetime_utils import ist_now


class ProjectSubtask(Base):
    __tablename__ = "project_subtasks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    title = Column(String(500), nullable=False)
    status = Column(String(50), default="Not Started")  # Options: Not Started, In Progress, Done
    assigned_to = Column(String(500), nullable=True)  # Optional employee username
    created_at = Column(DateTime(timezone=True), default=ist_now)

    project = relationship("Project", back_populates="subtasks")
    comments = relationship("SubtaskComment", back_populates="subtask", cascade="all, delete",order_by="SubtaskComment.commented_at.desc()")
    attachments = relationship("SubtaskAttachment", back_populates="subtask", cascade="all, delete")



class SubtaskLog(Base):
    __tablename__ = "subtask_logs"

    id = Column(Integer, primary_key=True, index=True)
    subtask_id = Column(Integer, ForeignKey("project_subtasks.id"))
    old_status = Column(String(20))
    new_status = Column(String(20))
    updated_by = Column(String(500))  # username or full name
    timestamp = Column(DateTime(timezone=True), default=ist_now)

    subtask = relationship("ProjectSubtask", backref="logs")

class SubtaskComment(Base):
    __tablename__ = "subtask_comments"
    id = Column(Integer, primary_key=True, index=True)
    subtask_id = Column(Integer, ForeignKey("project_subtasks.id"))
    subtask_id = Column(Integer, ForeignKey("project_subtasks.id"))
    comment_text = Column(String(1000)) 
    created_by = Column(String(100))
    commented_at = Column(DateTime(timezone=True), default=ist_now)

    subtask = relationship("ProjectSubtask", back_populates="comments")


class SubtaskAttachment(Base):
    __tablename__ = "subtask_attachments"
    id = Column(Integer, primary_key=True, index=True)
    subtask_id = Column(Integer, ForeignKey("project_subtasks.id"))
    filename = Column(String(255))
    filepath = Column(String(500))
    uploaded_by = Column(String(100))
    uploaded_at = Column(DateTime(timezone=True), default=ist_now)

    subtask = relationship("ProjectSubtask", back_populates="attachments")

