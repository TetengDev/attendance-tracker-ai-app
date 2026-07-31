# Repository Map

This map is for agents and humans who need to locate the active contracts quickly without rediscovering the tree.

## High-level layout

| Path | Role |
|---|---|
| `CLAUDE.md` | Agent operating guide, project-specific workflow rules, safety constraints, and current phase notes. |
| `README.md` | Quick project overview, setup, services, and check commands. |
| `docs/PLAN.md` | Full architecture and build plan. Treat §2 contracts as source-of-truth implementation specs. |
| `docs/ownership.toml` | Linear issue to path ownership map used by `scripts/check_ownership.py`. |
| `docs/contracts/ddl.md` | Data model and migration contract notes. |
| `docs/scan-topology.md` | Human-readable scan process topology decision record. |
| `backend/app/**` | Python backend package skeleton and contract modules. |
| `backend/tests/**` | Contract and fixture tests. |
| `frontend/packages/protocol/src/index.ts` | Generated TypeScript protocol constants. Do not hand-edit. |
| `infra/compose.yml` | Local Postgres, Redis cache, Redis store, and Mailpit stack. |
| `infra/postgres/init.sql` | Local Postgres initialization SQL. |
| `scripts/**` | Repository automation: protocol generation and ownership checks. |
| `Makefile` | Local check entrypoints. |
| `pyproject.toml` / `uv.lock` | Python project metadata and locked dependencies. |

## Core backend contracts

| Concern | Primary file | What to look for |
|---|---|---|
| Face engine interface | `backend/app/face/protocol.py` | `FaceEngine`, `Detection`, `LivenessResult`, `Embedding`, and `FakeFaceEngine`. Image boundaries are BGR uint8 HWC. |
| Settings registry | `backend/app/settings/registry.py` | `SETTINGS_SCHEMA`, setting enums, `default_settings()`, and `validate_setting()`. |
| Attendance resolver contract | `backend/app/attendance/decision_table.py` | Ordered first-match decision rules and independent attendance flags. The eventual resolver should implement this data table. |
| DDL invariants | `backend/app/db/base.py` and `docs/contracts/ddl.md` | Naming, extension, natural key, and migration conventions. |
| Error taxonomy | `backend/app/errors.py` | Stable domain error codes and response envelope types. |
| Kiosk API schemas | `backend/app/api/schemas/kiosk.py` | Shared scan request/result schema constants used to generate the TypeScript protocol. |
| Scan process topology | `backend/app/scan/runtime.py` and `docs/scan-topology.md` | API workers are model-free; dedicated scan workers own models behind a shared queue. |

## Tests and fixtures

| Path | Role |
|---|---|
| `backend/tests/test_face_protocol.py` | FaceEngine and FakeFaceEngine contract tests. |
| `backend/tests/test_attendance_decision_table.py` | Decision table order and required rows. |
| `backend/tests/test_db_contracts.py` | DDL/migration contract checks. |
| `backend/tests/test_scan_runtime_topology.py` | Scan topology invariants. |
| `backend/tests/test_factories.py` | Shared fixture factory behavior. |
| `backend/tests/factories/core.py` | Seeded org/location/device/person/schedule factories. |
| `backend/tests/factories/embeddings.py` | Synthetic 512-d embedding generation. |
| `backend/tests/factories/timezones.py` | Non-UTC timezone fixtures. |

## Generated and automation files

| Path | Role |
|---|---|
| `scripts/generate_protocol_ts.py` | Generates `frontend/packages/protocol/src/index.ts` from backend schema constants. |
| `scripts/check_ownership.py` | Verifies changed files are covered by `docs/ownership.toml`. |
| `Makefile.protocol` | Protocol generation helper. |

## Where to start for common tasks

| Task | Start here |
|---|---|
| Find the face engine contract | `backend/app/face/protocol.py` |
| Find the fake face engine for tests | `backend/app/face/protocol.py` |
| Find matcher/threshold settings | `backend/app/settings/registry.py` |
| Find attendance classification rules | `backend/app/attendance/decision_table.py` |
| Find the future resolver target | `backend/app/attendance/decision_table.py`; no resolver implementation exists yet. |
| Find local service ports | `infra/compose.yml` |
| Validate local work | `make check` |
| Check PR ownership scope | `uv run python scripts/check_ownership.py` |

