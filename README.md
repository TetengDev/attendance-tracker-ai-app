# Attendance Tracker AI App

Self-hosted attendance tracking for schools, offices, and similar organizations. The system identifies people by face, runs biometric processing on-premises, and records attendance without sending biometric data to an external service.

The current repository is still in scaffold/contract work. The implemented code is mainly shared backend contracts, local infrastructure, and test fixtures that unblock later parallel feature work.

## Current shape

- Backend: Python 3.13, `uv`, Pydantic, pytest, ruff, mypy.
- Face engine contract: `backend/app/face/protocol.py`.
- Settings registry: `backend/app/settings/registry.py`.
- Attendance decision table: `backend/app/attendance/decision_table.py`.
- Scan runtime topology: `backend/app/scan/runtime.py`.
- Local services: Postgres 17, two Redis roles, and Mailpit via `infra/compose.yml`.
- Generated frontend protocol package: `frontend/packages/protocol/src/index.ts`.

For the full architecture and phase plan, read `docs/PLAN.md`.

For a quick module-by-module map, read `docs/repository-map.md`.

## Prerequisites

- Python 3.13
- `uv`
- Docker with Docker Compose

The broader plan also expects Node/Bun for frontend work, but the current checked-in frontend surface is only the generated shared protocol package.

## Local setup

Install Python dependencies:

```bash
uv sync
```

Start local services:

```bash
docker compose -f infra/compose.yml up -d
```

Run the full local check:

```bash
make check
```

`make check` regenerates the TypeScript protocol, runs ruff, runs mypy, and runs pytest.

## Local services

`infra/compose.yml` starts:

| Service | Default port | Purpose |
|---|---:|---|
| Postgres 17 | 5432 | application database |
| Redis cache | 6379 | volatile cooldowns, rate limits, settings cache |
| Redis store | 6380 | durable-ish local jobs/admin sessions with AOF |
| Mailpit SMTP | 1025 | local mail capture |
| Mailpit UI | 8025 | inspect captured email |

The two Redis roles intentionally use different policies:

- cache: `volatile-ttl`, default `REDIS_CACHE_MAXMEMORY=128mb`
- store: `noeviction`, AOF, default `REDIS_STORE_MAXMEMORY=256mb`

## Development rules

- Do not commit `.env`, real face images, model weights, or downloaded evaluation corpora.
- Real face fixtures and evaluation corpora must stay in gitignored paths.
- Use `docs/ownership.toml` to keep PRs scoped to their Linear issue.
- Before human review, attach the PR to the counterpart Linear issue and run an independent PR-reviewer pass.

