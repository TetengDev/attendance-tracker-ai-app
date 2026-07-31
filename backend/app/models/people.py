from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship as orm_relationship
from sqlalchemy.types import Uuid

from backend.app.db.base import Base, created_at_column, updated_at_column, uuid_pk


class PersonKind(str, Enum):
    STUDENT = "student"
    STAFF = "staff"
    CONTRACTOR = "contractor"
    VISITOR = "visitor"


class GroupKind(str, Enum):
    ORG = "org"
    GRADE = "grade"
    SECTION = "section"
    TEAM = "team"
    CUSTOM = "custom"


class GuardianRelationship(str, Enum):
    MOTHER = "mother"
    FATHER = "father"
    GUARDIAN = "guardian"
    OTHER = "other"


class ContactChannel(str, Enum):
    SMS = "sms"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    NONE = "none"


class Person(Base):
    __tablename__ = "people"
    __table_args__ = (
        UniqueConstraint("external_id", name="uq_people_external_id"),
        CheckConstraint("display_name <> ''", name="display_name_non_empty"),
    )

    id: Mapped[UUID] = uuid_pk()
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kind: Mapped[PersonKind] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    group_memberships: Mapped[list[PersonGroup]] = orm_relationship(
        back_populates="person",
        cascade="all, delete-orphan",
    )
    guardians: Mapped[list[PersonGuardian]] = orm_relationship(
        back_populates="person",
        cascade="all, delete-orphan",
        foreign_keys="PersonGuardian.person_id",
    )


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("parent_group_id", "name", name="uq_groups_parent_name"),
        CheckConstraint("name <> ''", name="name_non_empty"),
    )

    id: Mapped[UUID] = uuid_pk()
    parent_group_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[GroupKind] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    parent: Mapped[Group | None] = orm_relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[Group]] = orm_relationship(back_populates="parent")
    memberships: Mapped[list[PersonGroup]] = orm_relationship(back_populates="group")


class PersonGroup(Base):
    __tablename__ = "person_groups"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "group_id",
            "effective_from",
            name="uq_person_groups_person_group_effective_from",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="effective_to_not_before_from",
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )
    group_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_column()

    person: Mapped[Person] = orm_relationship(back_populates="group_memberships")
    group: Mapped[Group] = orm_relationship(back_populates="memberships")

    def is_active_on(self, business_date: date) -> bool:
        return self.effective_from <= business_date and (
            self.effective_to is None or business_date <= self.effective_to
        )


class Guardian(Base):
    __tablename__ = "guardians"
    __table_args__ = (
        CheckConstraint("display_name <> ''", name="display_name_non_empty"),
        CheckConstraint(
            "email IS NOT NULL OR phone IS NOT NULL",
            name="guardian_has_contact_channel",
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preferred_channel: Mapped[ContactChannel] = mapped_column(
        String(32),
        nullable=False,
        default=ContactChannel.SMS,
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    wards: Mapped[list[PersonGuardian]] = orm_relationship(
        back_populates="guardian",
        cascade="all, delete-orphan",
        foreign_keys="PersonGuardian.guardian_id",
    )


class PersonGuardian(Base):
    __tablename__ = "person_guardians"
    __table_args__ = (
        UniqueConstraint("person_id", "guardian_id", name="uq_person_guardians_person_guardian"),
    )

    id: Mapped[UUID] = uuid_pk()
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )
    guardian_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("guardians.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship: Mapped[GuardianRelationship] = mapped_column(String(32), nullable=False)
    can_pick_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    receives_attendance_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_column()

    person: Mapped[Person] = orm_relationship(
        back_populates="guardians",
        foreign_keys=[person_id],
    )
    guardian: Mapped[Guardian] = orm_relationship(
        back_populates="wards",
        foreign_keys=[guardian_id],
    )


def active_group_memberships(
    memberships: list[PersonGroup],
    business_date: date,
) -> list[PersonGroup]:
    return [membership for membership in memberships if membership.is_active_on(business_date)]


def primary_group_for_date(
    memberships: list[PersonGroup],
    business_date: date,
) -> Group | None:
    active_memberships = active_group_memberships(memberships, business_date)
    primary_memberships = [membership for membership in active_memberships if membership.is_primary]
    selected_memberships = primary_memberships or active_memberships
    if not selected_memberships:
        return None
    return max(selected_memberships, key=lambda membership: membership.effective_from).group
