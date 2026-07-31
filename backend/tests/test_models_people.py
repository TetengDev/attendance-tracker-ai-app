from __future__ import annotations

from datetime import date
from typing import Any, cast

from sqlalchemy import Table

from backend.app.models.people import (
    Group,
    GroupKind,
    PersonGroup,
    active_group_memberships,
    primary_group_for_date,
)


def test_person_group_membership_preserves_mid_year_history() -> None:
    section_a = Group(kind=GroupKind.SECTION, name="7-A")
    section_b = Group(kind=GroupKind.SECTION, name="7-B")
    old_membership = PersonGroup(
        group=section_a,
        effective_from=date(2026, 6, 1),
        effective_to=date(2026, 8, 31),
    )
    new_membership = PersonGroup(
        group=section_b,
        effective_from=date(2026, 9, 1),
        effective_to=None,
    )
    memberships = [old_membership, new_membership]

    assert primary_group_for_date(memberships, date(2026, 8, 15)) is section_a
    assert primary_group_for_date(memberships, date(2026, 9, 15)) is section_b


def test_person_group_effective_to_is_inclusive() -> None:
    section = Group(kind=GroupKind.SECTION, name="7-A")
    membership = PersonGroup(
        group=section,
        effective_from=date(2026, 6, 1),
        effective_to=date(2026, 8, 31),
    )

    assert membership.is_active_on(date(2026, 8, 31))
    assert not membership.is_active_on(date(2026, 9, 1))


def test_people_models_encode_required_table_constraints() -> None:
    person_groups_table = cast(Table, PersonGroup.__table__)
    groups_table = cast(Table, Group.__table__)
    person_groups_constraints = {constraint.name for constraint in person_groups_table.constraints}
    groups_constraints = {constraint.name for constraint in groups_table.constraints}

    assert "uq_person_groups_person_group_effective_from" in person_groups_constraints
    assert "ck_person_groups_effective_to_not_before_from" in person_groups_constraints
    assert "uq_groups_parent_name" in groups_constraints


def test_group_primary_selection_prefers_primary_membership() -> None:
    advisory = Group(kind=GroupKind.SECTION, name="Advisory")
    club = Group(kind=GroupKind.CUSTOM, name="Chess Club")
    memberships = [
        PersonGroup(group=club, effective_from=date(2026, 6, 1), is_primary=False),
        PersonGroup(group=advisory, effective_from=date(2026, 6, 1), is_primary=True),
    ]

    assert active_group_memberships(memberships, date(2026, 6, 2)) == memberships
    assert primary_group_for_date(memberships, date(2026, 6, 2)) is advisory


def test_people_model_uses_uuid_primary_keys() -> None:
    assert cast(Any, Group.id).property.columns[0].server_default is not None
