from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from backend.app.db.base import Base, created_at_column, updated_at_column, uuid_pk
from backend.app.models.people import ContactChannel, Guardian, Person


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    RETRACTED = "retracted"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_notifications_dedupe_key"),
        CheckConstraint("dedupe_key <> ''", name="dedupe_key_non_empty"),
        Index("ix_notifications_person_date", "person_id", "business_date"),
        Index("ix_notifications_status", "status"),
    )

    id: Mapped[UUID] = uuid_pk()
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    period_label: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    guardian_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("guardians.id", ondelete="CASCADE"),
        nullable=False,
    )

    type: Mapped[str] = mapped_column(String(32), nullable=False)  # "absence", "tardiness", "retraction"
    status: Mapped[NotificationStatus] = mapped_column(
        String(32), nullable=False, default=NotificationStatus.PENDING
    )
    channel: Mapped[ContactChannel] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    message_body: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(256), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    person: Mapped[Person] = relationship(foreign_keys=[person_id])
    guardian: Mapped[Guardian] = relationship(foreign_keys=[guardian_id])


class NotificationRule(Base):
    __tablename__ = "notification_rules"
    __table_args__ = (
        CheckConstraint("delay_minutes >= 0", name="delay_minutes_non_negative"),
    )

    id: Mapped[UUID] = uuid_pk()
    group_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    person_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)  # "student", "staff", etc.
    trigger_status: Mapped[str] = mapped_column(String(32), nullable=False)  # "absent" or "late"
    delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channel: Mapped[ContactChannel] = mapped_column(String(32), nullable=False, default=ContactChannel.SMS)
    template: Mapped[Text] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
