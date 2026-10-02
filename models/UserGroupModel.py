"""
User groups: named groups of users for bulk assignment.
When assigning to a group, all members are assigned and the group name is stored.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Table, Boolean
from sqlalchemy.orm import relationship
from database import Base
from utils.datetime_utils import ist_now

user_group_members = Table(
    "user_group_members",
    Base.metadata,
    Column("user_group_id", Integer, ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class UserGroup(Base):
    __tablename__ = "user_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ist_now)
    updated_at = Column(DateTime(timezone=True), default=ist_now, onupdate=ist_now)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    members = relationship("User", secondary=user_group_members, backref="user_groups")
    created_by = relationship("User", foreign_keys=[created_by_id])
