# Attendance Tracker (AI) — Claude Code Context

## Project Overview

Self-hosted face-recognition attendance system for schools, offices, and similar establishments. A person walks up to a kiosk, the camera identifies them in under half a second, and attendance is logged and classified automatically (on-time / late / early-out / absent). Admins enroll faces, configure branding and attendance rules without a redeploy, and export reports.

Single organization, single tenant — many kiosk devices across many locations. Face recognition runs **fully offline on CPU**; no biometric data leaves the premises. **Governing jurisdiction: Philippines (RA 10173, Data Privacy Act).**

**Tech stack:** FastAPI (Python 3.13) · Postgres 17 · Redis 7 · ARQ behind a `JobQueue` protocol · React 19 + Vite 8 + TS · ONNX Runtime (SCRFD + ArcFace + MiniFASNet) · Docker Compose + Caddy
**Environment:** dev `https://localhost` (Caddy internal CA) · prod: self-hosted on the customer's LAN

> **Status: pre-implementation.** The architecture is in `docs/PLAN.md` (**revision 2**, rewritten after an adversarial architecture review and a source-verified fact-check). No application code exists yet.
>
> **Read `docs/PLAN.md` before writing anything.** In particular **§2 Contracts** — it holds the settings registry, `FaceEngine` Protocol, WS message contract, error taxonomy, natural keys, and classification decision table as *copyable specifications*. Copy them; do not invent your own.
>
> **§0 lists revision 1's refuted claims.** If something you remember about this project contradicts §0, §0 is right.

## Architecture

- **`docs/PLAN.md` is the source of truth.** This file is a quick-reference; the plan wins on any conflict.
- Monorepo: `backend/` (uv, Python) · `frontend/` (bun workspaces) · `models/` (vendored ONNX) · `infra/` · `docs/`
- **Two frontend bundles, deliberately separate:** `frontend/apps/kiosk` and `frontend/apps/admin`. The kiosk must never ship admin code.
- **The browser gates, the server recognizes.** The kiosk runs MediaPipe BlazeFace only to decide *when* a frame is worth sending. Embeddings are computed server-side, always.
- **Face matching is in-process NumPy brute force.** Exact by construction, and the only approach compatible with encrypted embeddings. **pgvector is not used** — encrypted columns are opaque to its operators, so it would have been an extension doing nothing reachable.
- **Attendance is a four-table split** — `attendance_events` (raw, immutable, append-only) → `expected_attendance` (materialized "what should have happened") → `attendance_records` (derived, rebuildable) + `attendance_overrides` (separate table, so records are genuinely disposable).
- **Two scan processes** behind a shared queue, with the model-free API on separate workers. One process means every deploy or OOM is a site-wide outage during the morning rush.
- **Settings are data, not code.** Scoped `device > location > org > code default`, Redis-cached, live-applied in under a second.
- **`FaceEngine` and `JobQueue` are Protocols** with implementations behind config — the licensing hedge and the ARQ-is-maintenance-only hedge respectively.

## Rules (Never Violate)

- **`resolve()` is the SOLE writer to `attendance_records`.** `mark_absences` enqueues resolve jobs; it never writes records itself. Two writers race and can mark someone absent who has already scanned.
- **NEVER let recomputation clobber an `attendance_overrides` row**, and never let expected-row re-expansion delete one by cascade.
- **NEVER UPDATE or DELETE `attendance_events`.** Corrections are new rows with `supersedes_event_id`.
- **NEVER derive `business_date` from the scanning device's timezone.** It belongs to the person's schedule context. Match events to expected rows by absolute UTC interval containment.
- **NEVER use Redis pub/sub as the mechanism for anything that must be correct** — it is at-most-once with no delivery guarantee. Gallery and settings consistency use a monotonic version that consumers poll; pub/sub only makes convergence fast.
- **NEVER respond to a scan before the event is durably written.** The kiosk will not replay an event it was told succeeded.
- **NEVER return, log, or export raw face embeddings.** They are partially invertible — published attacks reconstruct recognizable faces from ArcFace vectors.
- **NEVER store successful scan frames.** Failed-scan capture is opt-in, off by default, with a hard TTL.
- **NEVER write a `face_embeddings` row without an active consent** at the current `policy_version`.
- **NEVER hardcode a model path, threshold, or preprocessing constant at a call site.** Every tunable has a key in `SETTINGS_SCHEMA` (`docs/PLAN.md` §2.1). `buffalo_l` weights are **non-commercial research only**.
- **NEVER download models at runtime.** Vendor into `models/` with checksums.
- **NEVER commit `.env`, model weights, or any real face image.** Do not vendor LFW/CelebA/VGGFace2.
- **NEVER build emotion, mood, or engagement inference.** Prohibited outright in workplaces and schools under EU AI Act Art. 5(1)(f), and out of scope regardless of jurisdiction.
- **ALWAYS store timestamps as `timestamptz` in UTC**, and keep the three event times distinct: `client_captured_at` (untrusted), `server_received_at` (authoritative), `occurred_at` (derived).
- **ALWAYS enforce RBAC scoping in the query layer, not the UI.**

### MiniFASNet preprocessing — get this exactly right

The reference implementation uses `transforms.ToTensor()`. The correct contract is **BGR, HWC→CHW, float32 divided by 255.0, no mean/std**. Feeding raw 0–255 saturates the network and flattens the softmax, silently breaking spoof detection. Two crops are required — **2.7× and 4.0×**, read from the model filenames — so the client sends a ≥4.0× region plus bbox coords. Sum both 3-class softmaxes, divide by 2, take **index 1** as the live score, and assert that index at startup.

## Development Commands

> Not yet implemented — build these in Phase 0. Keep this section accurate as they land.

- `docker compose -f infra/compose.yml up -d` — Postgres 17, Redis (two policies), Caddy, Mailpit
- `make dev` — backend on :8000 + both frontends
- `make check` — `ruff` + `mypy --strict` + `pytest` + migration up/down round-trip (the gate before any commit)
- `make protocol` — regenerate TypeScript types from the Pydantic WS schema (must produce no diff in CI)
- `make test` — pytest against `FakeFaceEngine` (fast, no models)
- `pytest -m models` — model regression suite (slow, real ONNX, nightly)
- `make migrate` / `make migration m="..."` — Alembic
- `make seed` — admin user, one location, one device
- `uv run python -m app.face.bench` — per-stage latency
- `uv run python -m app.face.evaluate --extrapolate-to 5000` — FAR/FRR sweep, recommends a threshold

## Tech Stack Details / Coding Conventions

- **Python 3.13, pinned.** (3.12 is security-only; the old "opencv/onnx wheels don't exist higher" rationale is no longer true.) Managed by `uv` with a committed `uv.lock`.
- `ruff` (line-length 100) + `mypy --strict`. Pydantic v2 models use `extra="forbid"`.
- SQLAlchemy 2.0 **async** (asyncpg); no sync sessions in request paths.
- **Images are BGR uint8 HWC at every boundary** — never RGB, never float, until the model call itself.
- Errors: raise typed domain exceptions from `app/errors.py` with a **stable string code** from the taxonomy; translate to HTTP at the router boundary. Never leak a DB error to a client.
- Tests: plain pytest, long descriptive names. Time-dependent tests use `time-machine` and **must run at least once in a non-UTC timezone**.
- Frontend: TanStack Router + Query, Tailwind 4 + shadcn/ui. MediaPipe WASM is **vendored, never CDN**.

### Working in parallel with other agents

- **Only write files your issue's ownership line lists.** `docs/ownership.toml` maps issue → globs and CI enforces it.
- **If your issue is labelled `parallel-safe`, you may not author an Alembic migration.** N agents branching off the same `down_revision` produces N heads.
- Co-owned files (`conftest.py`, `SETTINGS_SCHEMA`, the Alembic chain, generated protocol types, the router registry) have a named owner — do not edit them opportunistically.

## Current Work Context

**Phase 0 (scaffold), in progress.** Done: revision-2 plan at `docs/PLAN.md`, `.gitignore`, agent teams, this file.

Next: uv project pinned to **3.13**, Docker Compose, Caddy, toolchain, bun workspace — then **Phase 0.5 (contracts)**, which blocks all parallel work, then **Phase 1, the face-engine spike**.

**Phase 1 is a hard gate.** No UI work starts until it proves: total pipeline latency, an ROC at FAR ≤ 0.1% **extrapolated to N=5000**, liveness separating real from print and screen replay, **and a real-lighting hallway test with ~20 volunteers**. The hallway test exists because the lab gate only proves the least likely thing to fail.

Known human-blocked items: TLS certs for LAN kiosks (`getUserMedia` needs a secure context), real faces for threshold tuning, the commercial-use decision on `buffalo_l`, and NPC registration + a named DPO.

**The Linear backlog is currently revision-1 vintage.** TEN-16 encodes the refuted MiniFASNet preprocessing, TEN-5/TEN-20 encode Python 3.12 and pgvector, and there are no issues for Phase 0.5. Reconcile before dispatching agents.

## Agent Workflow

- **Plan before executing.** Ask when two readings of a request lead to materially different work.
- Work is tracked as **Linear issues** (team `TEN` / Tengdev), executed by parallel subagents.
- Installed teams: `/development` (solutions-architect, tech-lead, senior-software-engineer, qa-engineer) · `/design` · `/security` (**use on anything touching biometrics, auth, or crypto**) · `/devops`.
- Run `make check` before reporting work complete. If tests fail, say so with the output.
- Atomic commits, one concern each. Never commit or push unless asked.

## Key Files Reference

| Path | Role |
|---|---|
| `docs/PLAN.md` | **Full architecture — read §0 and §2 first** |
| `backend/app/settings/registry.py` | `SETTINGS_SCHEMA` — six phases read it |
| `backend/app/face/protocol.py` | `FaceEngine` Protocol + `FakeFaceEngine` |
| `backend/app/face/liveness.py` | MiniFASNet — the corrected preprocessing |
| `backend/app/face/gallery.py` | NumPy index, matcher, versioned consistency |
| `backend/app/api/schemas/kiosk.py` | WS contract; TS is generated from it |
| `backend/app/errors.py` | Error taxonomy |
| `backend/app/attendance/resolver.py` | `resolve(..., as_of)` — sole writer |
| `backend/app/api/ws_kiosk.py` | Latency-critical path |
| `frontend/apps/kiosk/src/scan/useScanLoop.ts` | Gating, stability gate, WS client |
| `docs/ownership.toml` | Issue → path globs, CI-enforced |

## Off-Limits (Do Not Touch)

- `.env` — live GitHub and Linear tokens. Read via env vars; never print, echo, or commit the values.
- `.agentic-team/` and `.claude/{agents,commands,skills}/` — generated by `agentic-team`. Regenerate via the CLI, never hand-edit.
- `models/*.onnx` — vendored weights, license-restricted, gitignored.
- Any directory holding enrollment images or biometric data (`data/`, `storage/`, `uploads/`).
