# Face-Recognition Attendance Tracker — Architecture & Build Plan

## Context

`/Users/teng/Developer/Practical/Personal/Others/attendance-tracker-ai-app` is empty apart from an unfilled `CLAUDE.md` template. We are building, from scratch, a self-hosted attendance system that identifies people by face in under half a second and logs their attendance automatically — for schools, offices, and similar establishments.

The reference project `agentic-company-os` turned out to be a **catalog that generates Claude Code agent teams**, not app scaffolding. It contributes the build *process* (installable `developers`/`design`/`qa` subagent teams, three generic SKILL.md bodies, a Makefile/CI shape) — no application code.

**This deliverable is the plan plus a Linear backlog.** Per your decision, execution happens in a later session, where subagents pick up Linear issues in parallel.

### Locked decisions

| Decision | Choice |
|---|---|
| Face engine | Python + ONNX Runtime — SCRFD detect, ArcFace `w600k_r50` embed, MiniFASNet liveness. Fully offline, CPU, zero per-scan cost. |
| Model licensing | **Swappable `FaceEngine` Protocol.** Start on `buffalo_l`; model path + preprocessing are config, so replacement is a config change + re-embed job. |
| Deployment | Single organization, self-hosted. Many devices and locations, one tenant. |
| v1 features | Passive liveness · shifts & late detection · multi-device/location · notifications — all in scope. |
| Admin config | Branding + kiosk text + attendance rules as settings rows, live-applied without redeploy. |
| Sequencing | Plan now, execute later, tracked as Linear issues for parallel agents. |

### Verified environment

Apple M5 Pro (arm64), macOS. `uv`, Node 26, bun, Docker 29.6.1, libpq present. **Pin Python 3.12.13** — the lowest-risk point where every wheel in the chain (`onnxruntime` 1.28, `onnx` 1.22, `opencv-python`, `numpy` 2.5, `scikit-image` 0.26) exists as an arm64 binary. Not 3.14: `onnx` only reaches it via an abi3 wheel and `opencv-python` is the shakiest link, for zero gain.

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12 + FastAPI + Pydantic v2 + uvicorn | The face engine is Python and sits on the 500 ms critical path. Any other API language forces an IPC hop and a second image serialization per scan. |
| ORM | SQLAlchemy 2.0 async (asyncpg) + Alembic | |
| DB | Postgres 17 + pgvector (Docker Compose) | Relational-heavy domain. pgvector for offline analytics and duplicate detection — **not** the hot path. |
| Vector search | **In-process NumPy brute force** | 5,000 people × 5 embeddings = 25k × 512 × f32 = 51 MB; one BLAS `sgemv` in 2–6 ms. Exact by construction — ANN recall misses concentrate exactly at the decision boundary, where a silent false-reject is undebuggable in the field. Also the only option compatible with encrypted embeddings. |
| Cache / locks / broker | Redis 7 | Atomic scan cooldowns (`SET NX EX`), rate limits, sessions, settings cache + pub/sub invalidation. |
| Jobs | **ARQ** (redis-backed, asyncio-native) | Same runtime as FastAPI, built-in cron. Celery's asyncio story is still awkward; RQ has no async. |
| Frontend | React 19 + TS + Vite 6, TanStack Router/Query, Tailwind 4 + shadcn/ui | Two separate bundles: `apps/kiosk` and `apps/admin` — the kiosk must not ship admin JS. |
| Client face gating | `@mediapipe/tasks-vision` BlazeFace (WASM+SIMD), **vendored not CDN** | ~1–3 ms/frame. Not the browser `FaceDetector` API (Chromium-only, flagged). |
| Export | `xlsxwriter` (`constant_memory=True`), WeasyPrint (in the worker container) | |
| Tooling | `uv` + `uv.lock`, ruff, mypy strict, pytest; bun for frontend | |

**Repo layout:** `/backend` (uv) · `/frontend` (bun workspaces) · `/models` (vendored ONNX + checksums) · `/infra` (compose, Caddy) · `/docs`

---

## 1. Scan pipeline — target < 500 ms end to end

**The browser gates; the server recognizes.** Never compute embeddings client-side: anyone with devtools could submit an arbitrary embedding, and you'd have to ship the gallery to the kiosk. The client's only job is deciding "is this frame worth 100 ms of server time?"

**Client gate** (every frame, 320×240 offscreen canvas): exactly one face → bbox ≥ 8% of frame and inter-ocular ≥ 90 px → centered within 20% → variance-of-Laplacian sharpness floor (motion blur is the #1 cause of bad embeddings) → mean luma in [40, 220] → **stability gate: bbox IoU ≥ 0.9 across 3 frames and ≥ 120 ms elapsed**. Throttle to one submission per 400 ms; hard-stop after a match until the face leaves frame.

On pass, send the bbox **expanded 2.0×** (MiniFASNet needs that context), letterboxed to 480×480, JPEG q=0.85 → 18–35 KB. Send a 2-frame burst 150 ms apart; server scores both, takes the better, and requires both to agree on identity or drops to ambiguous.

**Transport: WebSocket** `wss://host/ws/kiosk`, one per kiosk, device JWT at connect, 20 s heartbeat. Chosen over HTTP POST for: no per-attempt handshake, and **server→client progressive feedback** (`detected → checking → Welcome, Maria`) which makes 350 ms *feel* instant. Also carries backpressure and live settings push. Keep `POST /scan` as fallback. Start with JSON+base64 for debuggability; go binary only if measured.

**Server pipeline, in order:**

```
1. Auth / token bucket        ~0.2 ms
2. JPEG decode (cv2)          ~2-4 ms
3. SCRFD detect               ~12-25 ms   det_size=(384,384); reject 0 or >1 face, det_score < 0.60
4. 5-point align → 112×112    ~1 ms       ArcFace canonical similarity transform
5. LIVENESS (MiniFASNet)      ~4-8 ms     ← before recognition: 5× cheaper, and a spoof must never touch the gallery
6. ArcFace embed (r50)        ~25-40 ms   512-d, L2-normalized
7. Gallery matmul             ~2-6 ms     top-5 cosine
8. Decision + Redis cooldown  ~1 ms
9. Respond, THEN enqueue DB write + record resolution
```

Server wall clock ~50–90 ms; ~220–380 ms end-to-end on LAN.

**Liveness:** two Apache-2.0 models (`2.7_80x80_MiniFASNetV2`, `4_0_0_80x80_MiniFASNetV1SE`), 80×80 **BGR uint8→float32 with no mean/std normalization** (real gotcha — the reference feeds raw BGR). Average the two softmaxes; accept at `live_score ≥ 0.75`. **Verify the "live" class index empirically** — wrong class ordering is the single most common implementation bug here.

`liveness_mode ∈ {off, monitor, enforce}` as a setting. **Ship at `monitor`.** Enforcing on day one, before the threshold is tuned against your actual kiosk lighting, produces a lockout incident. Monitor mode logs what *would* have been blocked so you tune on real data.

**Match thresholding** — cosine on L2-normalized embeddings, every number a settings row:

| Band | Action |
|---|---|
| `top1 ≥ 0.45` and `top1 − top2_other_person ≥ 0.05` | **Accept** |
| `top1 ≥ 0.45`, margin `< 0.05` | **Ambiguous** — "step closer". Log it; this is your enrollment-hygiene signal (twins, siblings, bad enrollment) |
| `0.38 ≤ top1 < 0.45` | **Low confidence** — reject (default for students) or accept-with-tap-confirm (default for offices) |
| `top1 < 0.38` | **Unknown** — offer PIN/QR fallback |

0.45 is a starting point, not gospel. **1:N identification needs a higher threshold than the 1:1 verification numbers you'll find quoted**, because you take a max over N candidates and false-accept probability grows roughly linearly with gallery size. Tune via `evaluate.py` (Phase 1): ≥100 identities × ≥6 images, enroll 3 / probe 3, sweep 0.20→0.70, **pick where FAR ≤ 0.1%** (a false accept is attendance fraud; a false reject is a retry). If the resulting FRR > 3%, enrollment quality is the problem, not the threshold. Log `top1_score` on every scan so the ROC can be re-derived from production data after 30 days and retuned without redeploy.

**Anti-double-scan:** `scan_cooldown_seconds` (default 60) via `SET scan:cd:{person}:{scope} NX EX` — atomic and correct across workers. `cooldown_scope` defaults to **location**, not device, otherwise someone walks to the next turnstile and double-punches. Plus per-device scan rate (2/s) and **unknown-face rate limit (10/min → 60 s lockout)**, which is what blocks gallery probing.

---

## 2. Data model

All `timestamptz` stored UTC. UUID PKs except high-volume append tables (bigint identity, for index locality). Soft-delete on entities; **hard delete on biometric tables**.

**People:** `people` (external_id, names, role, status, pin_hash, qr_secret, custom_fields jsonb) · `groups` (self-referencing `parent_group_id` so Grade 7 → 7-A nests; `type: class|section|department|team`) · `person_groups` (M2M **with `effective_from`/`effective_to`** — students change sections mid-year and last year's report must still be right) · `guardians` / `person_guardians`.

**Biometrics:** `enrollment_assets` (kind `upload|photo_capture|live_capture`, sha256, capture_pose, quality/det/blur/brightness scores, `purge_after`) · `face_embeddings` (`vector` **bytea, AES-GCM encrypted**, model_name/version, pose, quality, `is_active`, `source`) · `consents` (consent_type, granted_by self/guardian, relationship, method, `policy_version`, ip, revoked_at).

> **Multiple embeddings per person is mandatory** — target 5 (frontal, ±20° yaw, slight up, one with glasses if worn). Require ≥3 before `enrollment_complete`.

**Devices:** `locations` (**`timezone` IANA required** — all schedule math is location-local) · `devices` (location, `direction: in|out|bidirectional`, token_hash + prefix, pairing_code, status, last_seen, `settings_override` jsonb, allowed_cidrs) · `device_heartbeats` (7-day retention; drives the offline-kiosk alert you will absolutely need).

**Scheduling:** `shifts` (start/end time, `crosses_midnight`, grace_in/out, `absent_after_minutes`, min_dwell, break) · `schedules` · `schedule_rules` (weekday → shift, optional `period_label` for schools) · `schedule_assignments` (**resolution order: person > group > location > org default**) · `calendar_days` (holiday/closure/half_day/special) · `person_exceptions` (leave/sick/excused/field_trip — what turns an Absent into an Excused, **editable after the fact**).

**Attendance — the load-bearing three-table split:**

1. **`attendance_events`** — raw, immutable, append-only. person_id (nullable — unknown faces get a row), device, location, `occurred_at`, `business_date`, event_type (`check_in|check_out|scan|denied_spoof|denied_low_confidence|unknown_face|manual`), match_score, match_margin, liveness_score, det_score, latency_ms, `idempotency_key` unique. **Never UPDATE or DELETE** — corrections are new rows with `supersedes_event_id`.

2. **`expected_attendance`** — the materialization trick that makes Absent tractable. person × business_date × shift × period, with absolute `expected_start_at`/`expected_end_at`. A nightly job expands schedules ± calendar ± exceptions 14 days ahead. **Absent then becomes "an expected row with no satisfying event"** — one indexable `WHERE NOT EXISTS`, and every report becomes a left join instead of a `generate_series` nightmare.

3. **`attendance_records`** — derived classification, a **rebuildable cache**. status (`on_time|late|absent|excused|early_out|incomplete|holiday|not_scheduled|present_unscheduled`), late_minutes, worked_minutes, `is_manual_override`, `compute_version`. Must be fully reconstructible from events + expected + overrides. **`is_manual_override` is inviolable** — recomputation never clobbers it. Retrofitting that after someone's payroll correction vanishes is a bad day.

**Config & ops:** `settings` (dotted key, jsonb value, **scope `org|location|device` with resolution device > location > org > code default**, Redis-cached with pub/sub invalidation → live in < 1 s) · `admin_users` (argon2id, role, `scope_group_ids[]` so teachers see only their sections, totp_secret) · `admin_sessions` · `audit_log` (**append-only with a `prev_hash`/`hash` chain** — 10 lines, makes tampering detectable in a system holding biometrics) · `notifications` (with **`dedupe_key` unique** — what stops the 3 a.m. duplicate-alert incident) · `notification_rules` · `report_jobs` · `assets`.

A typed `SETTINGS_SCHEMA` registry in code drives both server-side validation and auto-rendering of the admin UI, so adding a setting is a backend-only change.

---

## 3. Attendance state machine

`resolve(person_id, business_date)` is a **pure, idempotent function**: reads `expected_attendance` + `attendance_events` (± overnight window), writes `attendance_records`. Pure means you can re-run it after a schedule edit, a manual correction, or a bug fix and it converges. Triggered per accepted event via ARQ with job key `resolve:{person}:{date}` and a 2 s debounce (a burst of scans collapses to one computation), plus a nightly full sweep.

**`business_date` is defined explicitly, never inferred from UTC:** `(occurred_at in location.tz − day_boundary_hour).date()`, where `day_boundary_hour` defaults to 00:00 and is set to ~04:00 for overnight-shift sites. Overnight shifts are the classic trap — a 22:00–06:00 shift check-in and check-out land on different calendar dates, so pairing operates on the `expected_start_at`/`expected_end_at` **interval**, not the date.

**Classification** given expected `[S,E]`, grace-in `Gi`, grace-out `Go`, absent-after `A`:

| Condition | Status |
|---|---|
| `person_exceptions` covers the date | `excused` |
| Non-working per `calendar_days` / `schedule_rules` | `holiday` / `not_scheduled` |
| Events but no expected row | `present_unscheduled` |
| First IN ≤ `S + Gi` | `on_time` |
| `S + Gi` < first IN ≤ `S + A` | `late`, `late_minutes = in − (S + Gi)` |
| No IN by `S + A`, none later | `absent` |
| Last OUT < `E − Go` | `early_out` |
| IN, no OUT by `E + auto_close` | `incomplete` → optionally auto-closed |

`late` and `early_out` aren't mutually exclusive — model `status` plus boolean `was_late` / `left_early` so reports count both.

**Entry/exit pairing** — configurable, because schools and offices genuinely differ:
- `device_direction` — the device declares IN or OUT (turnstile-style, cleanest)
- `toggle` — first scan IN, next scan after `min_dwell_minutes` is OUT (absorbs "scanned twice at the door")
- `first_last` — first event of the day IN, last OUT, everything between ignored. **Default for `role = student`**; simplest and most robust, and what most schools actually want.

Pairing runs over the person's event stream regardless of which device produced each event, so an IN at Building A / OUT at Building B is allowed but flagged `location_mismatch` — locking to a single location would break every real multi-building site.

**Generating Absent** (the scan that never happens) — three ARQ crons:
- `expand_schedules` — 00:15 local per location + on-demand on any schedule/calendar/exception change. Idempotent upsert 14 days ahead; deletes stale future rows, never touches past rows.
- `mark_absences` — **every 5 minutes**, not nightly, because the alert must be timely: a parent wants the SMS at 08:45. Absence is provisional — a late scan flips `absent → late` through the same resolver, with a `retraction` notification template.
- `close_open_records` — 23:50 local; auto-closes `incomplete`, emits daily summaries.
- `recompute_range(from, to, person_ids?)` — admin-triggered escape hatch for "the schedule was wrong for three weeks". **Build it in Phase 5, not later.**

---

## 4. API surface

All under `/api/v1`. Admin routes: session cookie + CSRF. Kiosk routes: device JWT.

```
auth/         login logout me · totp/{setup,verify} · password/{change,reset/*}
admin-users/  CRUD
devices/      CRUD · {id}/pairing-code · {id}/revoke · pair · token/refresh · {id}/heartbeats
locations/ groups/ people/   CRUD · people/import (CSV) · {id}/attendance · {id}/groups · {id}/exceptions
guardians/    CRUD · people/{id}/guardians
enrollment    people/{id}/enrollment/{upload,capture,session} · WS /ws/enroll
              people/{id}/enrollment/session/{sid}/commit · {id}/enrollment/quality
              people/{id}/embeddings (metadata only) · DELETE {eid} · rebuild
              enrollment/validate · enrollment/duplicates
scan          WS /ws/kiosk · POST /scan · POST /scan/pin · GET /kiosk/bootstrap
scheduling    shifts/ schedules/ schedules/{id}/rules · schedule-assignments/ · calendar-days/
              schedules/preview   ← expected rows before saving
attendance/   events · records · records/{id}/override · manual · recompute · live
              WS /ws/dashboard
settings/     GET · GET /schema (drives admin UI) · PATCH · branding/logo · reset/{key}
reports/      catalogue · {key}/run · {key}/export · report-jobs/{id}[/download]
notifications notification-rules/ · notifications/ · {id}/retry · test · templates/{key}
compliance    people/{id}/consents[/{cid}/revoke] · {id}/erase · {id}/data-export
              audit-log · audit-log/verify · retention/policy · retention/run
ops           health · health/deep · metrics · system/face-engine
```

---

## 5. Frontend surfaces

**Kiosk** (`/kiosk`, separate PWA bundle, fullscreen): `getUserMedia` 1280×720, offscreen gating loop, vendored MediaPipe WASM, persistent WS with backoff reconnect, and an **IndexedDB offline queue** replayed on reconnect (safe via `idempotency_key`). Overlay ring states (searching → face found → hold still → checking → result), large result card with photo/name/IN-OUT/late badge, audio + haptic feedback, always-visible PIN/QR fallback, Wake Lock, hidden long-press + PIN diagnostics panel. All text/colors/logo from `/kiosk/bootstrap`, live-updated via WS push.

> **Non-obvious blocker: `getUserMedia` requires a secure context.** `localhost` is exempt; `http://192.168.1.50` is **not**. Every LAN kiosk needs a real cert — plan **Caddy with an internal CA** (or mkcert installed per kiosk) from Phase 4. Discovering this at deployment is the most common way this class of project slips a week.

**Admin dashboard** (`/admin`): live board (present/late/absent/not-yet-arrived by location and group) with WS-pushed scan feed; device health strip (a dead kiosk visible in under a minute); anomaly tray for spoof denials, unknown faces (one-click "enroll this person"), and ambiguous matches; quick manual check-in and mark-excused.

**Enrollment** (`/admin/people/{id}/enroll`) — three tabs, one commit step:
1. **Upload** — drag-drop N images with inline per-image validation (face found? sharp? large enough? multiple faces? matches someone else?). Reject bad ones *before* commit.
2. **Take a picture** — admin webcam, single shot, same validation.
3. **Live capture (multi-angle)** — guided: "look straight → turn slightly left → turn slightly right → look up". Coarse yaw from the 5-point landmarks auto-captures when the pose target is hit. 5–8 frames total.

Commit shows the crops, per-image quality, a **duplicate check against the gallery** (blocks silently creating two records for one person — a real and common integrity failure), and consent capture. **Enrollment cannot complete without a consent row.**

**Reports** (`/admin/reports`): picker → parameter form → paginated preview → export. Long exports become jobs with a progress toast. Saved presets; scheduled-reports tab.

**Settings** (`/admin/settings`): auto-generated from `/settings/schema`. Sections — Branding (with **live kiosk preview**), Kiosk (greeting, language, feedback style, result duration), Attendance rules (grace, absent-after, cooldown, pairing strategy, required fields), Face engine (**threshold slider showing the historical FAR/FRR curve derived from logged scores** — this is what makes the threshold tunable in practice), Liveness, Notifications, Retention & privacy, Devices, Users & roles.

---

## 6. Reports & export

| Report | Grain | Audience |
|---|---|---|
| Daily attendance register | person × date | Both |
| Period/class register | person × date × period | Schools |
| Timesheet / Payroll summary | person × date / pay period | Offices |
| Tardiness · Absence summary | person × range | Both |
| Consecutive-absence (truancy) · Perfect attendance | person | Schools |
| Headcount by hour | location × hour | Offices |
| **Muster / fire roll** | currently checked-in by location | **Safety-critical: one click, must work degraded** |
| Exception report | overrides, location mismatches, auto-closes, spoof denials | Compliance |
| Device/scan health | device × day | Ops |

Schools measure **attendance rate as % of expected sessions** per section per period with a truancy threshold; offices measure **hours, overtime, late-minute accumulation** per individual or department. Both are parameterized SQL over `expected_attendance LEFT JOIN attendance_records` — the materialized expected rows turn "attendance rate" into a clean `count(present) / count(expected)`.

One `ReportDefinition` per report (key, param schema, query builder, typed column spec); three renderers over the same row iterator:
- **CSV** — `StreamingResponse` over a server-side cursor, constant memory at 1 M rows. **Emit a UTF-8 BOM** or Excel-on-Windows mangles accented names (guaranteed bug report otherwise).
- **XLSX** — `xlsxwriter` `constant_memory=True`; frozen header, autofilter, **typed cells** (dates as dates, minutes as numbers), summary + detail sheets, conditional formatting.
- **PDF** — WeasyPrint over Jinja templates shared with email. Branded header from settings, filter criteria in the footer, generated-at/by. *Caveat: needs Pango/Cairo — run report generation in the worker container even in dev.*

Exports over ~5,000 rows go async → `report_jobs` → expiring signed URL (24 h). **Every export writes an audit row** — you must be able to answer "who took a copy of the student roster."

---

## 7. Privacy & security

This is where a school deployment actually gets stopped, so it's built in from Phase 2, not bolted on.

**What to store:**
- **Embeddings: always** — the operational data.
- **Original enrollment images: yes, encrypted, with explicit consent.** Not sentimental — **ArcFace embeddings are model-version-locked**. When you swap the recognition model (and per your licensing decision, you may), old embeddings are worthless. Without originals, that's physically re-enrolling 5,000 people; with them, it's a background job. Document it as a consented purpose and give admins a switch to disable it.
- **Scan frames: never, by default.** Pixels are embedded and discarded. Two exceptions behind settings with hard TTLs: `store_failed_scans` (unknown/spoof, default **off**, 72 h) and `debug_capture_mode` (auto-expires 24 h, audit-logged on enable). Successful scan images add no value and multiply breach surface by scans-per-day.
- **Never expose raw vectors over the API.** `GET /people/{id}/embeddings` returns metadata only. Face embeddings are partially invertible — published attacks reconstruct recognizable faces from ArcFace vectors. Treat a vector like a password hash that *can* be un-hashed.

**Encryption:** envelope-encrypt embeddings and enrollment bytes with AES-256-GCM, per-record DEK wrapped by a KEK from env/secret file, `encryption_key_id` on the row for rotation. **Consequence: a stolen `pg_dump` contains no usable biometric data** — the single most persuasive line in a privacy review, for ~80 lines of code. (This is also why the gallery lives in memory rather than pgvector: encrypted columns are opaque to pgvector operators.) TLS everywhere including LAN. KEK never in repo or DB; startup fails loudly if absent.

**Device auth, two-stage** (a forever-token on a wall-mounted tablet is a liability): admin issues an 8-char pairing code (15 min, single use) → device exchanges it for an opaque 32-byte token (stored server-side only as HMAC-SHA256 + 6-char display prefix) → device exchanges *that* for a **15-minute scan JWT** per session. Revocation is instant at refresh, immediate for open sockets via a Redis revocation set checked on heartbeat. Devices reach only scan endpoints and `/kiosk/bootstrap`; a compromised kiosk yields nothing beyond what its screen already shows, and unknown-face rate limiting blocks enumeration.

**Admin auth:** argon2id (t=3, m=64 MiB, p=4); opaque session IDs in Redis, `HttpOnly`/`Secure`/`SameSite=Lax`, 8 h idle / 24 h absolute, rotated on privilege change; CSRF double-submit; login lockout with backoff. **TOTP mandatory for any role that can export PII.** RBAC `owner|admin|hr|supervisor|viewer` with `scope_group_ids` **enforced in the query layer, not the UI**.

**Consent, retention, deletion:**
- **Consent before capture.** No embedding may be written without an active `biometric_enrollment` consent referencing the current `policy_version` — DB check plus application guard. Re-consent required when the policy version changes.
- **BIPA** (statutory damages, private right of action — the highest-dollar risk here, and cheap to comply with if built now): a written, publicly available biometric policy with a retention schedule → ship it as a versioned settings-editable page at `/privacy/biometrics`; written informed consent before collection; **destruction at purpose-satisfied or 3 years after last interaction, whichever is first**; no sale; reasonable standard of care.
- **GDPR** treats embeddings as Art. 9 special-category data: explicit lawful basis, a **DPIA** (Art. 35 — biometric monitoring of students/employees triggers it; it's a document, not code), minimization, Arts. 15/17/20.
- **Retention settings:** `embeddings_retain_days_after_inactive` 1095 (BIPA-aligned) · enrollment images 1095 · unknown-face images 72 h · attendance events/records 2555 (payroll/regulatory — these are timestamps, not biometrics) · audit log 2555, never less than the data it describes. Nightly `run_retention` writes an audit row per purge batch.
- **Erasure** (`POST /people/{id}/erase`): hard-DELETE embeddings and enrollment assets, shred blobs, **purge the in-memory index immediately via pub/sub** (not at next restart), null PII on `people`, but **keep attendance history pseudonymized** — it's payroll/regulatory data with an independent lawful basis. Document exactly this reasoning in the privacy policy.
- **DSAR export**: ZIP with person record, events, records, consent and notification history, and enrollment images — but **not raw embeddings** (a security risk to hand out and meaningless to the subject); disclose their count and model version in a manifest instead.

**Two things flagged hardest:**
1. **`buffalo_l` is non-commercial-research-licensed** (MIT covers InsightFace's *code*, not the weights; commercial use needs a license from insightface.ai). Per your decision we build on it now — which makes the `FaceEngine` Protocol with model path and preprocessing as **data, not code**, a hard architectural requirement rather than a nicety. Phase 1 also benchmarks a permissive candidate (ONNX Model Zoo ArcFace ResNet100) and records the accuracy delta, so the swap decision later is a number, not a guess.
2. **A non-biometric alternative is required**, not optional. Several jurisdictions effectively forbid compelling biometric collection, and some people cannot use face recognition reliably. The PIN/QR fallback is what makes the consent genuinely voluntary — build it in Phase 4, alongside the kiosk.

---

## 8. Testing strategy

The central move: **`FaceEngine` is a Protocol and ~95% of the suite runs against `FakeFaceEngine`.** Everything but the model becomes ordinary deterministic software.

- **L1 — pure logic, no models, no DB.** Matcher bands, margin rule, cosine math, quality scoring, `business_date`, schedule priority resolution, the whole `resolve()` classifier. `hypothesis` properties: a normalized vector scores 1.0 against itself; adding an embedding never lowers that person's best score; `resolve()` is idempotent; classification is monotonic in arrival time.
- **L2 — pipeline and API against the fake.** `fake.next_result(person="alice", score=0.62, liveness=0.91)` lets you test cooldowns, rate limits, liveness enforce/monitor branching, ambiguity, unknown-face lockout, the WS protocol, event writing, record resolution, and notification triggering with **zero images and perfect determinism**. Postgres via testcontainers, each test in a rolled-back transaction.
- **L3 — model regression**, `@pytest.mark.models`, nightly. **Embedding stability**: fixed 112×112 `.npy` in → assert 512-d output matches a checked-in golden within `atol=1e-3`. This catches onnxruntime upgrades, model swaps, and preprocessing drift — the failures that silently degrade production accuracy without throwing. Plus accuracy regression (`TAR@FAR=1e-3 ≥ baseline − 0.01`, fail the build), liveness sanity, and a p95 < 150 ms latency guard.

**Fixture data:** do **not** vendor LFW/CelebA/VGGFace2 — several are research-use-only or withdrawn, and checking real people's faces into a biometrics repo is exactly what this app's privacy policy forbids. Use **synthetic 512-d vectors** with controlled intra/inter-class structure for L1/L2 (the matcher needs no pixels at all); for L3, ~50–100 synthetic or rights-cleared images stored outside the repo, with the tiny precomputed golden `.npy` files checked in as the actual assertions.

**Determinism traps to design around:** JPEG round-trips aren't bit-stable across libraries — assert on `.npy`, never re-decoded JPEG. `cv2.resize` and `PIL.Image.resize` differ at the same nominal interpolation — pin one preprocessing path. onnxruntime varies with thread count — fix `intra_op_num_threads=1` in tests. Time-dependent tests use `time-machine` and **run at least once in a non-UTC location timezone**; a UTC-only suite will not catch your timezone bugs.

**E2E (Playwright/Chromium)** — the concrete answer to "how do you test a camera without a face": `--use-fake-device-for-media-capture --use-file-for-fake-video-capture=fixtures/alice.y4m`. Chromium feeds the Y4M to `getUserMedia` as a real camera, exercising the MediaPipe gating loop, WS protocol, and result UI genuinely end to end. Record clips for "alice walks up", "phone-screen replay", "empty frame".

**Load (k6/locust):** 20 kiosks × 1 scan / 3 s against a 5,000-person gallery, p95 < 500 ms, no cooldown leakage across workers. This is also how you discover that N uvicorn workers each loading three ONNX models eats N × ~600 MB RAM and contends on threads — **the fix is a single dedicated scan process with the model-free API on separate workers, decided in Phase 4 rather than in production.**

---

## 9. Build phases

Each phase is independently verifiable. Phase 1 de-risks the face engine before any UI exists.

| # | Phase | Est. | Done when |
|---|---|---|---|
| 0 | **Scaffold** — uv @ 3.12.13, compose (PG17+pgvector, Redis 7), Caddy, ruff/mypy/pytest, bun workspace, `CLAUDE.md`, agentic-company-os teams installed | 0.5 d | `docker compose up` reaches PG + Redis; `uvicorn` serves `/health`; empty suite passes |
| 1 | **Face engine spike — CLI only, no web** | 2–3 d | One command over two image folders prints per-stage latency **< 100 ms total**, an ROC with a recommended threshold at FAR ≤ 0.1%, and liveness scores separating a real photo from a phone-screen replay. **No UI work starts until signed off.** |
| 2 | **Data model, migrations, core API** — all tables, settings registry + Redis resolver, admin auth (argon2id/TOTP/RBAC), audit middleware, consent model | 3–4 d | Migrations up/down clean; CRUD people/locations/groups/devices over HTTP; every mutation lands in `audit_log`; RBAC scoping proven by tests |
| 3 | **Enrollment + gallery index** — upload/capture/live-capture, per-image validation, encrypted storage, `GalleryIndex` + pub/sub, duplicate detection, rebuild | 3 d | Enroll 20 people from a folder; index loads in < 2 s; a probe returns the right identity; duplicate enrollment blocked; enrolling without consent → 422 |
| 4 | **Kiosk scan loop** — WS endpoint, device pairing, full pipeline, cooldowns, React kiosk with MediaPipe gating, PIN/QR fallback, offline queue, **TLS via Caddy internal CA** | 4–5 d | Two physical devices scan over `https://` on LAN, identity in **< 500 ms p95 client-measured**; cooldown suppresses a repeat; a printed photo denied in enforce mode; 30 s network loss queues and replays with no duplicates |
| 5 | **Schedules + state machine** — shifts/rules/assignments with priority, calendar, exceptions, `expand_schedules`, pure `resolve()`, `mark_absences`, `close_open_records`, `recompute_range`, all three pairing strategies | 4 d | Table-driven suite (frozen time, ≥40 cases) covers on-time/late/early-out/absent/excused/holiday/incomplete/overnight/**both DST transitions**/multi-location/multi-period; `recompute_range` over a month is idempotent and preserves overrides |
| 6 | **Admin dashboard + configurable UI** — SPA shell, live board WS, people/enrollment UI, device management, schema-driven settings, branding with live preview, manual overrides | 5 d | Changing logo/color/greeting updates a **running kiosk within 2 s with no redeploy**; changing `grace_in_minutes` changes a new scan's classification; a teacher account sees only their groups |
| 7 | **Reports & export** — definitions, three renderers, async jobs, presets, expiry + audit | 3 d | Every report renders and exports to CSV/XLSX/PDF with branding; a 50k-row CSV streams under 200 MB RSS; every export audit-logged |
| 8 | **Notifications** — rules engine, Jinja templates, SMTP (`aiosmtplib` + Mailpit in dev), pluggable SMS (Twilio first), outbox with retry/backoff/dedupe | 2–3 d | An absence produces **exactly one** guardian email within the offset; a late arrival sends a retraction; a provider outage retries without double-sending |
| 9 | **Privacy & hardening** — envelope encryption + rotation runbook, retention jobs, erasure + DSAR, audit chain verify, CSP, `pip-audit`/`bun audit`, biometric policy page, DPIA, restore drill | 3 d | `pg_dump` has no readable biometric data; erasure clears DB + disk + live index while history survives pseudonymized; `/audit-log/verify` passes; restore-from-backup succeeds |
| 10 | **Packaging & ops** — prod compose, healthchecks, Prometheus + Grafana, JSON logging with request IDs, backup cron, runbooks | 2 d | A clean machine goes `git clone` → working kiosk in under 30 min following only the written runbook |

**~6–7 weeks solo.** Phases 1 and 5 are where estimates break.

---

## 10. Linear integration & parallel agent execution

**Setup** (one-time, requires your OAuth login — I can't do this unattended):
```
claude mcp add --transport http linear-server https://mcp.linear.app/mcp
# then run /mcp in a Claude Code session to complete OAuth
```

**Backlog structure:** one Linear **project** ("Attendance Tracker v1"), one **milestone per phase** above, and issues at story grain (½–2 days each) so a subagent can own one end to end.

Every issue carries:
- **Labels** — `phase:N` · `area:{face-engine,backend,frontend-kiosk,frontend-admin,data,jobs,security,reports,notifications,infra,docs}` · `parallel-safe` or `serialized` · `needs-human` (OAuth, certs, real-face testing, model licensing)
- **Blocked-by links** — the real dependency graph, so an agent can query "issues with no unresolved blockers in phase N" and claim work without collisions
- **A file-ownership line** — the paths this issue may write. Two `parallel-safe` issues must never list overlapping paths; that invariant is what makes simultaneous subagents safe.
- **Acceptance criteria** — copied from the phase "Done when" column, narrowed to the story, written as a runnable check

**Parallelism map** (what can genuinely run simultaneously):
- Phase 1 is **serialized and blocking** — everything downstream depends on its threshold and latency numbers.
- Phase 2 fans out wide: each table group, auth, settings registry, and audit middleware are near-independent once the migration skeleton exists.
- Phases 3 + 5 can run concurrently (enrollment vs. scheduling touch disjoint modules).
- Phase 4 backend and Phase 4 kiosk frontend split cleanly across the WS message contract — **write that contract as a shared TypeScript + Pydantic schema in the first issue of the phase**, then both sides proceed in parallel against it.
- Phases 6, 7, 8 are largely independent of each other once Phase 5 lands.

**Bootstrapping the backlog:** a first execution session creates the Linear issues from this plan via the MCP tools, then subsequent sessions dispatch subagents (the `developers` / `design` / `qa` teams installed from `agentic-company-os` in Phase 0) against ready issues.

---

## Critical files (create in this order)

| Path (under repo root) | Role |
|---|---|
| `backend/app/face/engine.py` | `FaceEngine` Protocol + ONNX impl (SCRFD decode, ArcFace align/embed, MiniFASNet liveness). **Everything depends on this interface; model path + preprocessing are config, not code** — that's what makes the licensing swap cheap. |
| `backend/app/face/gallery.py` | In-memory NumPy `GalleryIndex`, matcher, threshold/margin decision, Redis pub/sub invalidation |
| `backend/app/models/{people,attendance,scheduling,settings}.py` | SQLAlchemy schema. The events / expected / records split is the load-bearing decision. |
| `backend/app/attendance/resolver.py` | Pure idempotent `resolve(person_id, business_date)` + pairing strategies |
| `backend/app/api/ws_kiosk.py` | WS scan endpoint — pipeline, cooldown, rate limiting, event writing on the latency-critical path |
| `backend/app/settings/registry.py` | Typed `SETTINGS_SCHEMA` — drives validation *and* admin UI generation |
| `frontend/apps/kiosk/src/scan/useScanLoop.ts` | MediaPipe gating, stability gate, throttling, WS client |
| `models/` + `models/checksums.txt` | Vendored ONNX. **Never download at runtime** — first-boot GitHub fetches are a guaranteed field failure. |
| `CLAUDE.md` | Fill the existing template: stack, commands, the buffalo_l licensing constraint, "never log or return raw embeddings", "never store successful scan frames" |

---

## Verification

**Phase 1 gate (the one that matters most)** — before any UI exists:
```bash
cd backend && uv run python -m app.face.bench   --iterations 100
cd backend && uv run python -m app.face.evaluate --enroll fixtures/enroll --probe fixtures/probe
```
Expect: per-stage p50/p95 with total < 100 ms on the M5; an FAR/FRR table with a recommended threshold at FAR ≤ 0.1%; liveness scores separating a real photo from a replay of it. **If total latency exceeds 100 ms**, tune `det_size` and `intra_op_num_threads` and try the int8-quantized `w600k_r50` before proceeding.

**Per-phase:** `make check` → `ruff` + `mypy --strict` + `pytest` (fake engine, fast) + migration up/down round-trip. Model regression suite (`pytest -m models`) nightly.

**End-to-end, from Phase 4:**
1. `docker compose up`, `make seed` → admin user + one location + one device
2. Enroll yourself through all three paths — upload, take-a-picture, guided live capture
3. Open the kiosk on a second device over `https://` on the LAN, scan, confirm identity in < 500 ms and a record in the admin live board
4. Hold a **printed photo and a phone screen** to the camera — both denied in enforce mode
5. Change logo, primary color, and greeting in admin → kiosk updates within 2 s, no redeploy
6. Change `grace_in_minutes` → a new scan reclassifies on-time ↔ late
7. Pull the network for 30 s, scan 3×, restore → exactly 3 records, no duplicates
8. Export the daily register to CSV/XLSX/PDF; confirm branding, and an audit row per export
9. `POST /people/{id}/erase` → embeddings gone from DB, disk, and the live index; attendance history survives pseudonymized
10. `pg_dump` and grep — no readable biometric data

**Playwright E2E** (fake Y4M camera) and the k6 load scenario (20 kiosks × 5,000-person gallery, p95 < 500 ms) run before each release.
