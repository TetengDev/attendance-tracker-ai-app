# Attendance Tracker (AI) — Claude Code Context

## Project Overview

Self-hosted face-recognition attendance system for schools, offices, and similar establishments. A person walks up to a kiosk, the camera identifies them in under half a second, and attendance is logged and classified automatically (on-time / late / early-out / absent). Admins enroll faces, configure branding and attendance rules without a redeploy, and export reports.

Single organization, single tenant — but many kiosk devices across many locations. Face recognition runs **fully offline on CPU**; no biometric data ever leaves the premises.

**Tech stack:** FastAPI (Python 3.12) · Postgres 17 + pgvector · Redis 7 · ARQ · React 19 + Vite + TS · ONNX Runtime (SCRFD + ArcFace + MiniFASNet) · Docker Compose + Caddy
**Environment:** dev `https://localhost` (Caddy internal CA) · prod: self-hosted on the customer's LAN

> **Status: pre-implementation.** The architecture is fully specified in `docs/PLAN.md` and approved. No application code exists yet. **Read `docs/PLAN.md` before writing anything** — it holds the data model, scan pipeline, thresholds, and phase breakdown that this file only summarizes.

## Architecture

- **`docs/PLAN.md` is the source of truth.** This file is a quick-reference; the plan wins on any conflict.
- Monorepo: `backend/` (uv, Python) · `frontend/` (bun workspaces) · `models/` (vendored ONNX) · `infra/` (compose, Caddy) · `docs/`
- **Two frontend bundles, deliberately separate:** `frontend/apps/kiosk` and `frontend/apps/admin`. The kiosk must never ship admin code.
- **The browser gates, the server recognizes.** The kiosk runs MediaPipe BlazeFace only to decide *when* a frame is worth sending. Embeddings are computed server-side, always.
- **Face matching is in-process NumPy brute force**, not pgvector. Exact by construction, and the only approach compatible with encrypting embeddings at rest. pgvector exists for offline analytics and duplicate detection only.
- **Attendance is a three-table split** — `attendance_events` (raw, immutable, append-only) → `expected_attendance` (materialized "what should have happened") → `attendance_records` (derived, rebuildable classification). Materializing expected rows is what makes "Absent" — a classification with no triggering scan — a single indexable query.
- **`resolve(person_id, business_date)` is a pure, idempotent function.** Re-running it after any edit must converge on the same answer.
- **Settings are data, not code.** Branding, kiosk text, and attendance rules live in a `settings` table, scoped `device > location > org > code default`, Redis-cached with pub/sub invalidation so changes reach a running kiosk in under a second.
- **`FaceEngine` is a Protocol** with model paths and preprocessing as config. See the licensing rule below — this is not a nicety.

## Rules (Never Violate)

- **NEVER return, log, or export raw face embeddings.** They are partially invertible — published attacks reconstruct recognizable faces from ArcFace vectors. Treat a vector like a password hash that *can* be un-hashed. Embedding endpoints return metadata only.
- **NEVER store successful scan frames.** Pixels are embedded and discarded. Failed-scan capture is opt-in, off by default, with a hard TTL.
- **NEVER write a `face_embeddings` row without an active `consents` row** of type `biometric_enrollment` at the current `policy_version`. This is a BIPA/GDPR requirement, enforced at both the DB and application layer.
- **NEVER hardcode a model path or preprocessing constant at a call site.** `buffalo_l` weights are licensed for **non-commercial research only** (InsightFace's MIT license covers their code, not their weights). Everything must stay swappable via config.
- **NEVER download models at runtime.** Vendor them into `models/` with checksums; a first-boot fetch from GitHub is a guaranteed field failure.
- **NEVER commit `.env`, model weights, or any real face image.** Do not vendor LFW/CelebA/VGGFace2 — several are research-use-only, and checking real faces into a biometrics repo is exactly what this app's privacy policy forbids.
- **NEVER let recomputation clobber `is_manual_override`.** Someone's payroll correction vanishing is a very bad day.
- **NEVER UPDATE or DELETE `attendance_events`.** Corrections are new rows with `supersedes_event_id`.
- **ALWAYS store timestamps as `timestamptz` in UTC**, and derive `business_date` explicitly from the location's IANA timezone — never infer it from UTC.
- **ALWAYS enforce RBAC scoping in the query layer, not the UI.**

## Development Commands

> Not yet implemented — these are the interfaces to build in Phase 0. Keep this section accurate as they land.

- `docker compose -f infra/compose.yml up -d` — Postgres 17 + pgvector, Redis 7, Caddy, Mailpit
- `make dev` — backend on :8000 + both frontends via Vite
- `make check` — `ruff` + `mypy --strict` + `pytest` + migration up/down round-trip (the gate before any commit)
- `make test` — pytest against `FakeFaceEngine` (fast, no models)
- `pytest -m models` — model regression suite (slow, real ONNX, nightly)
- `make migrate` / `make migration m="..."` — Alembic
- `make seed` — admin user, one location, one device
- `uv run python -m app.face.bench` — per-stage face pipeline latency
- `uv run python -m app.face.evaluate` — FAR/FRR sweep, recommends a match threshold

## Tech Stack Details / Coding Conventions

- **Python 3.12.13, pinned.** Not 3.14 — `onnx` only reaches it via an abi3 wheel and `opencv-python` is the shakiest link in the chain, for zero gain. Managed by `uv` with a committed `uv.lock`.
- `ruff` (line-length 100) + `mypy --strict`. Pydantic v2 models use `extra="forbid"`.
- SQLAlchemy 2.0 **async** (asyncpg) throughout; no sync sessions in request paths.
- Every threshold, grace period, and cooldown is a **settings row with a code default**, never a literal at a call site.
- Errors: raise typed domain exceptions in services; translate to HTTP at the router boundary. Never leak a DB error to a client.
- Tests are plain pytest functions with long descriptive names. Time-dependent tests use `time-machine` and **must run at least once in a non-UTC timezone** — a UTC-only suite will not catch your timezone bugs.
- Frontend: TanStack Router + Query, Tailwind 4 + shadcn/ui, Zustand for kiosk-local state. MediaPipe WASM is **vendored, never CDN** — the kiosk must work offline.

## Current Work Context

**Phase 0 (scaffold), in progress.** Done so far: approved plan at `docs/PLAN.md`, `.gitignore`, agent teams installed, this file.

Next: uv project pinned to 3.12.13, Docker Compose, Caddy, lint/type/test wiring, bun workspace — then **Phase 1, the face-engine spike**.

**Phase 1 is a hard gate. No UI work starts until it is signed off**, proving: total pipeline latency < 100 ms on this M5, an ROC with a recommended threshold at FAR ≤ 0.1%, and liveness scores that separate a real face from a phone-screen replay.

Known human-blocked items: TLS certs for LAN kiosks (`getUserMedia` needs a secure context — `http://192.168.x.x` silently has no camera), real faces for threshold tuning, and the commercial-use decision on `buffalo_l`.

## Agent Workflow

- **Plan before executing.** Ask when two readings of a request lead to materially different work.
- Work is tracked as **Linear issues** (team `TEN` / Tengdev) so subagents can run in parallel. Each issue carries `phase:N` and `area:*` labels, blocked-by links, and a **file-ownership line** — two `parallel-safe` issues must never list overlapping write paths. That invariant is what makes concurrent agents safe; respect it.
- Installed teams — dispatch with the slash command, or call an agent directly:
  - `/development` — solutions-architect, tech-lead, senior-software-engineer, qa-engineer (max 3 concurrent)
  - `/design` — product-designer (kiosk and admin UI)
  - `/security` — security-reviewer (**use this on anything touching biometrics, auth, or crypto**)
  - `/devops` — devops-engineer (infra, compose, CI)
- Run `make check` before reporting work complete. If tests fail, say so with the output.
- Atomic commits, one concern each. Never commit or push unless asked.

## Key Files Reference

| Path | Role |
|---|---|
| `docs/PLAN.md` | **Full architecture — read this first** |
| `backend/app/face/engine.py` | `FaceEngine` Protocol + ONNX impl. Everything depends on this interface. |
| `backend/app/face/gallery.py` | In-memory NumPy index, matcher, threshold/margin decision |
| `backend/app/attendance/resolver.py` | The pure, idempotent classification state machine |
| `backend/app/api/ws_kiosk.py` | WebSocket scan endpoint — the latency-critical path |
| `backend/app/settings/registry.py` | Typed `SETTINGS_SCHEMA`; drives validation *and* admin UI generation |
| `frontend/apps/kiosk/src/scan/useScanLoop.ts` | MediaPipe gating, stability gate, throttling, WS client |
| `models/checksums.txt` | Vendored ONNX weights + hashes |

## Off-Limits (Do Not Touch)

- `.env` — live GitHub and Linear tokens. Read via env vars; never print, echo, or commit the values.
- `.agentic-team/` — generated bundle + `bundle.lock.json` from `agentic-company-os`. Regenerate via the CLI, never hand-edit.
- `.claude/agents/`, `.claude/commands/`, `.claude/skills/` — likewise generated by `agentic-team export project`.
- `models/*.onnx` — vendored weights, license-restricted, gitignored.
- Any directory holding enrollment images or biometric data (`data/`, `storage/`, `uploads/`).
