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
| `scripts/**` | Repository automation: protocol generation, ownership checks, face engine CLI (bench, evaluate, liveness_check). |
| `Makefile` | Local check entrypoints. |
| `pyproject.toml` / `uv.lock` | Python project metadata and locked dependencies. |

## Core backend contracts

| Concern | Primary file | What to look for |
|---|---|---|
| Face engine interface | `backend/app/face/protocol.py` | `FaceEngine`, `Detection`, `LivenessResult`, `Embedding`, and `FakeFaceEngine`. Image boundaries are BGR uint8 HWC. |
| Face engine implementation | `backend/app/face/engine.py` | `ONNXFaceEngine` — wraps SCRFD (detection), ArcFace (embedding), MiniFASNet (liveness). |
| Gallery index | `backend/app/face/gallery.py` | `GalleryIndex` (NumPy brute-force matcher), `MatchResult`, `MatchDecision`. |
| Settings registry | `backend/app/settings/registry.py` | `SETTINGS_SCHEMA`, setting enums, `default_settings()`, and `validate_setting()`. |
| Attendance resolver contract | `backend/app/attendance/decision_table.py` | Ordered first-match decision rules and independent attendance flags. |
| Server scan pipeline | `backend/app/scan/pipeline.py` | `run_scan_pipeline()` — detect → liveness → embed → match → decide. |
| Scan sessions | `backend/app/scan/sessions.py` | Location-aware scan sessions for fixed and roaming devices. |
| WebSocket scan endpoint | `backend/app/api/ws_scan.py` | Kiosk WebSocket: JWT handshake, gallery loading, burst frame processing, heartbeat. |
| DDL invariants | `backend/app/db/base.py` and `docs/contracts/ddl.md` | Naming, extension, natural key, and migration conventions. |
| Error taxonomy | `backend/app/errors.py` | Stable domain error codes and response envelope types. |
| Kiosk API schemas | `backend/app/api/schemas/kiosk.py` | Shared scan request/result schema constants used to generate the TypeScript protocol. |
| Scan process topology | `backend/app/scan/runtime.py` and `docs/scan-topology.md` | API workers are model-free; dedicated scan workers own models behind a shared queue. |

## Tests and fixtures

| Path | Role |
|---|---|
| `backend/tests/test_face_protocol.py` | FaceEngine and FakeFaceEngine contract tests. |
| `backend/tests/test_gallery_index.py` | Gallery index matching and versioned consistency tests. |
| `backend/tests/test_scan_pipeline.py` | Server scan pipeline tests (all rejection paths, cooldown, matching). |
| `backend/tests/test_ws_scan.py` | WebSocket scan endpoint integration tests (handshake, heartbeat, burst). |
| `backend/tests/test_attendance_decision_table.py` | Decision table order and required rows. |
| `backend/tests/test_db_contracts.py` | DDL/migration contract checks. |
| `backend/tests/test_scan_runtime_topology.py` | Scan topology invariants. |
| `backend/tests/test_scan_sessions.py` | Scan session lifecycle tests. |
| `backend/tests/test_enrollment_api.py` | Enrollment endpoint tests. |
| `backend/tests/test_consent_enforcement.py` | Biometric consent gate tests. |
| `backend/tests/test_factories.py` | Shared fixture factory behavior. |
| `backend/tests/factories/core.py` | Seeded org/location/device/person/schedule factories. |
| `backend/tests/factories/embeddings.py` | Synthetic 512-d embedding generation. |
| `backend/tests/factories/timezones.py` | Non-UTC timezone fixtures. |

## Generated and automation files

| Path | Role |
|---|---|
| `scripts/generate_protocol_ts.py` | Generates `frontend/packages/protocol/src/index.ts` from backend schema constants. |
| `scripts/check_ownership.py` | Verifies changed files are covered by `docs/ownership.toml`. |
| `scripts/bench.py` | Face engine latency benchmarking (SCRFD, ArcFace, MiniFASNet). |
| `scripts/evaluate.py` | ROC threshold sweep, FMR/FNMR, FAR extrapolation to N=5000. Blocking gate (exit 1 if threshold < 0.45). |
| `scripts/liveness_check.py` | Single-image liveness verification CLI. |
| `Makefile.protocol` | Protocol generation helper. |

## Where to start for common tasks

| Task | Start here |
|---|---|
| Find the face engine contract | `backend/app/face/protocol.py` |
| Find the ONNX engine implementation | `backend/app/face/engine.py` |
| Find the fake face engine for tests | `backend/app/face/protocol.py` |
| Find matcher/threshold settings | `backend/app/settings/registry.py` |
| Find attendance classification rules | `backend/app/attendance/decision_table.py` |
| Find the scan pipeline | `backend/app/scan/pipeline.py` |
| Find the WebSocket scan endpoint | `backend/app/api/ws_scan.py` |
| Find local service ports | `infra/compose.yml` |
| Validate local work | `make check` |
| Benchmark face engine | `uv run python scripts/bench.py` |
| Run threshold evaluation | `uv run python scripts/evaluate.py` |
| Check PR ownership scope | `uv run python scripts/check_ownership.py` |

