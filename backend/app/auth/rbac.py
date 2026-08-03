from __future__ import annotations

from datetime import date

from sqlalchemy import Select, exists, false, select

from backend.app.models.admin import AdminRole, AdminUser
from backend.app.models.people import Person, PersonGroup

UNSCOPED_ROLES = frozenset({AdminRole.OWNER, AdminRole.ADMIN, AdminRole.HR})


def can_export_pii(admin_user: AdminUser) -> bool:
    return AdminRole(admin_user.role) in {AdminRole.OWNER, AdminRole.ADMIN, AdminRole.HR}


def scoped_people_query(
    admin_user: AdminUser,
    *,
    business_date: date,
) -> Select[tuple[Person]]:
    base_query = select(Person).where(Person.is_active.is_(True))
    if AdminRole(admin_user.role) in UNSCOPED_ROLES:
        return base_query
    if not admin_user.scope_group_ids:
        return base_query.where(false())
    scoped_membership = (
        exists()
        .where(PersonGroup.person_id == Person.id)
        .where(PersonGroup.group_id.in_(admin_user.scope_group_ids))
        .where(PersonGroup.effective_from <= business_date)
        .where(
            (PersonGroup.effective_to.is_(None)) | (PersonGroup.effective_to >= business_date),
        )
    )
    return base_query.where(scoped_membership)
