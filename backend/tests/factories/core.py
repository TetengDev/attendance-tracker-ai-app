from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5


def stable_uuid(kind: str, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"attendance-tracker:{kind}:{key}")


@dataclass(frozen=True)
class OrgFactory:
    key: str = "default-org"
    name: str = "Demo Organization"

    @property
    def id(self) -> UUID:
        return stable_uuid("org", self.key)


@dataclass(frozen=True)
class LocationFactory:
    key: str = "main-campus"
    name: str = "Main Campus"
    timezone: str = "Asia/Manila"

    @property
    def id(self) -> UUID:
        return stable_uuid("location", self.key)


@dataclass(frozen=True)
class DeviceFactory:
    key: str = "kiosk-1"
    mode: str = "fixed"
    form_factor: str = "tablet"
    location: LocationFactory = LocationFactory()

    @property
    def id(self) -> UUID:
        return stable_uuid("device", self.key)


@dataclass(frozen=True)
class PersonFactory:
    key: str = "person-1"
    display_name: str = "Test Person"
    external_id: str | None = None

    @property
    def id(self) -> UUID:
        return stable_uuid("person", self.key)
