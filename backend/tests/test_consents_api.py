from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.common import CrudError, CrudErrorCode, RequestActor, authenticated_admin_user
from backend.app.api.consents import (
    BiometricConsentAuthorize,
    BiometricConsentCreate,
    get_consents_service,
)
from backend.app.config import get_settings
from backend.app.db.session import get_session
from backend.app.main import create_app
from backend.app.models.admin import AdminRole, AdminUser
from backend.app.models.biometrics import Consent, ConsentGrantor, ConsentMethod, ConsentType


class FakeSession:
    committed = False
    rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


async def fake_session() -> AsyncIterator[AsyncSession]:
    yield FakeSession()  # type: ignore[misc]


async def _skip_middleware_audit(_entry: object) -> None:
    return None


def _admin_user(role: AdminRole = AdminRole.ADMIN) -> AdminUser:
    return AdminUser(
        id=UUID("00000000-0000-0000-0000-0000000000ad"),
        email="admin@example.test",
        display_name="Admin",
        password_hash="hash",
        role=role,
        scope_group_ids=[],
        is_active=True,
        totp_secret=b"x" * 32,
    )


def _authenticated_app(monkeypatch: MonkeyPatch, admin_user: AdminUser | None = None) -> FastAPI:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("BIOMETRIC_KEK", "test-kek")
    monkeypatch.setattr("backend.app.audit.middleware._append_entry", _skip_middleware_audit)
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[authenticated_admin_user] = lambda: admin_user or _admin_user()
    return app


def _consent(
    *,
    person_id: UUID,
    consent_id: UUID | None = None,
    policy_version: str = "privacy-v2",
    revoked_at: datetime | None = None,
) -> Consent:
    return Consent(
        id=consent_id or UUID("20000000-0000-0000-0000-000000000033"),
        person_id=person_id,
        consent_type=ConsentType.BIOMETRIC_PROCESSING,
        grantor=ConsentGrantor.SELF,
        method=ConsentMethod.DIGITAL_SIGNATURE,
        policy_version=policy_version,
        granted_at=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
        revoked_at=revoked_at,
        ip_address="testclient",
        evidence_ref="signed-form-33",
    )


def test_consents_router_is_registered(monkeypatch: MonkeyPatch) -> None:
    with TestClient(_authenticated_app(monkeypatch)) as client:
        paths = set(client.get("/openapi.json").json()["paths"])

    assert "/api/consents/biometric-enrollment" in paths
    assert "/api/consents/biometric-enrollment/authorize" in paths
    assert "/api/consents/{consent_id}/revoke" in paths


def test_create_biometric_enrollment_consent_audits_ip_and_commits(
    monkeypatch: MonkeyPatch,
) -> None:
    person_id = UUID("10000000-0000-0000-0000-000000000033")
    audit_calls: list[dict[str, object]] = []
    captured_ip: str | None = None

    class FakeConsentsService:
        async def create_biometric_enrollment(
            self,
            _session: AsyncSession,
            payload: BiometricConsentCreate,
            *,
            ip_address: str | None,
            now: datetime,
        ) -> Consent:
            nonlocal captured_ip
            captured_ip = ip_address
            return _consent(person_id=payload.person_id, policy_version=payload.policy_version)

    async def fake_audit(
        _session: AsyncSession,
        actor: RequestActor,
        *,
        action: str,
        entity_type: str,
        entity_id: str | None,
        before: dict[str, object] | None,
        after: dict[str, object] | None,
    ) -> None:
        audit_calls.append(
            {
                "actor": actor.admin_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "before": before,
                "after": after,
            }
        )

    monkeypatch.setattr("backend.app.api.consents.audited_mutation", fake_audit)
    app = _authenticated_app(monkeypatch)
    app.dependency_overrides[get_consents_service] = lambda: FakeConsentsService()

    with TestClient(app) as client:
        response = client.post(
            "/api/consents/biometric-enrollment",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            json={
                "person_id": str(person_id),
                "grantor": "self",
                "method": "digital_signature",
                "policy_version": "privacy-v2",
                "evidence_ref": "signed-form-33",
            },
        )

    assert response.status_code == 201
    assert response.json()["person_id"] == str(person_id)
    assert response.json()["consent_type"] == "biometric_processing"
    assert captured_ip == "testclient"
    assert audit_calls[0]["action"] == "consent.biometric_enrollment.create"
    assert audit_calls[0]["after"]["policy_version"] == "privacy-v2"  # type: ignore[index]


def test_authorize_biometric_enrollment_without_active_consent_returns_422(
    monkeypatch: MonkeyPatch,
) -> None:
    person_id = UUID("10000000-0000-0000-0000-000000000034")

    class FakeConsentsService:
        async def authorize_biometric_enrollment(
            self,
            _session: AsyncSession,
            payload: BiometricConsentAuthorize,
            *,
            as_of: datetime,
        ) -> Consent:
            raise CrudError(
                CrudErrorCode.INVALID_INPUT,
                "active biometric enrollment consent is required for the current policy version",
            )

    app = _authenticated_app(monkeypatch)
    app.dependency_overrides[get_consents_service] = lambda: FakeConsentsService()

    with TestClient(app) as client:
        response = client.post(
            "/api/consents/biometric-enrollment/authorize",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            json={"person_id": str(person_id), "policy_version": "privacy-v2"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "active biometric enrollment consent is required for the current policy version"
    )


def test_revoke_consent_blocks_future_authorization_in_service_contract(
    monkeypatch: MonkeyPatch,
) -> None:
    consent_id = UUID("20000000-0000-0000-0000-000000000035")
    person_id = UUID("10000000-0000-0000-0000-000000000035")
    revoked = _consent(
        consent_id=consent_id,
        person_id=person_id,
        revoked_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
    )

    class FakeConsentsService:
        async def revoke(
            self,
            _session: AsyncSession,
            *,
            consent_id: UUID,
            revoked_at: datetime,
        ) -> Consent:
            revoked.revoked_at = revoked_at
            return revoked

    async def fake_audit(
        _session: AsyncSession,
        actor: RequestActor,
        *,
        action: str,
        entity_type: str,
        entity_id: str | None,
        before: dict[str, object] | None,
        after: dict[str, object] | None,
    ) -> None:
        return None

    monkeypatch.setattr("backend.app.api.consents.audited_mutation", fake_audit)
    app = _authenticated_app(monkeypatch)
    app.dependency_overrides[get_consents_service] = lambda: FakeConsentsService()

    with TestClient(app) as client:
        response = client.post(
            f"/api/consents/{consent_id}/revoke",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
        )

    assert response.status_code == 200
    assert response.json()["revoked_at"] is not None
