from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Self

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.audit.chain import AuditEntry
from backend.app.audit.middleware import REQUEST_ID_HEADER, AuditMiddleware
from backend.app.models.audit import AuditActorKind


def test_audit_middleware_skips_read_only_requests(monkeypatch: MonkeyPatch) -> None:
    captured: list[AuditEntry] = []
    app = _app_with_routes(captured, monkeypatch)

    with TestClient(app) as client:
        response = client.get("/things/1")

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER]
    assert captured == []


def test_audit_middleware_records_exactly_one_mutating_request(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: list[AuditEntry] = []
    app = _app_with_routes(captured, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/things",
            headers={
                REQUEST_ID_HEADER: "req-client",
                "x-actor-kind": "admin",
                "x-actor-id": "00000000-0000-0000-0000-000000000029",
            },
        )

    assert response.status_code == 201
    assert response.headers[REQUEST_ID_HEADER] == "req-client"
    assert len(captured) == 1
    assert captured[0].actor_kind == AuditActorKind.ADMIN
    assert captured[0].action == "POST /things"
    assert captured[0].entity_type == "things"
    assert captured[0].request_id == "req-client"
    assert captured[0].after == {"status_code": 201, "path": "/things", "method": "POST"}
    assert captured[0].ip_address == "testclient"


def test_audit_middleware_records_failed_mutating_request(monkeypatch: MonkeyPatch) -> None:
    captured: list[AuditEntry] = []
    app = _app_with_routes(captured, monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete("/things/1")

    assert response.status_code == 409
    assert len(captured) == 1
    assert captured[0].action == "DELETE /things/1"
    assert captured[0].after == {"status_code": 409, "path": "/things/1", "method": "DELETE"}


def test_audit_middleware_records_unhandled_mutating_exception(monkeypatch: MonkeyPatch) -> None:
    captured: list[AuditEntry] = []
    app = _app_with_routes(captured, monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch("/things/1")

    assert response.status_code == 500
    assert len(captured) == 1
    assert captured[0].action == "PATCH /things/1"
    assert captured[0].after == {"status_code": 500, "path": "/things/1", "method": "PATCH"}


def _app_with_routes(captured: list[AuditEntry], monkeypatch: MonkeyPatch) -> FastAPI:
    async def fake_append(_session: AsyncSession, entry: AuditEntry) -> None:
        captured.append(entry)

    monkeypatch.setattr("backend.app.audit.middleware.append_audit_entry", fake_append)
    monkeypatch.setattr("backend.app.audit.middleware.get_session_factory", _session_factory)

    app = FastAPI()
    app.add_middleware(AuditMiddleware)

    @app.get("/things/{thing_id}")
    async def get_thing(thing_id: str) -> dict[str, str]:
        return {"id": thing_id}

    @app.post("/things", status_code=201)
    async def create_thing() -> dict[str, str]:
        return {"id": "created"}

    @app.delete("/things/{thing_id}", status_code=409)
    async def delete_thing(thing_id: str) -> dict[str, str]:
        return {"id": thing_id, "status": "blocked"}

    @app.patch("/things/{thing_id}")
    async def patch_thing(thing_id: str) -> dict[str, str]:
        raise RuntimeError(f"cannot patch {thing_id}")

    return app


def _session_factory() -> object:
    return _FakeSessionFactory()


class _FakeSessionFactory:
    def __call__(self) -> _FakeSession:
        return _FakeSession()


class _FakeSession:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    def __getattr__(self, _name: str) -> Any:
        raise AssertionError("fake session should only be passed through to append_audit_entry")
