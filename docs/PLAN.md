# Face-Recognition Attendance Tracker — Architecture & Build Plan

**Revision 2** — rewritten 2026-07-31 after an adversarial architecture review and an external fact-check. Revision 1's refuted claims are listed in §0 so nothing carries forward silently.

## Context

`/Users/teng/Developer/Practical/Personal/Others/attendance-tracker-ai-app` — a self-hosted attendance system that identifies people by face in under half a second and logs attendance automatically, for schools, offices, and similar establishments. Single organization, many kiosks, many locations. Face recognition runs fully offline on CPU; no biometric data leaves the premises.

Revision 1 was approved and seeded as 78 Linear issues (TEN-5…TEN-82). It was then reviewed two ways: a solutions-architect pass over the design, and a source-verified fact-check of its technical and legal claims. Both found real defects. **This document is the corrected plan and, deliberately, a reference document rather than a narrative** — §2 contains copyable contracts so parallel implementation agents copy specifications instead of inventing them.

### Locked decisions

| Decision | Choice |
|---|---|
| Face engine | ONNX Runtime — SCRFD detect, ArcFace `w600k_r50` embed, MiniFASNet liveness. Offline, CPU. |
| Model licensing | Swappable `FaceEngine` Protocol. Start on `buffalo_l`; model path + preprocessing are config. |
| Deployment | Single organization, self-hosted. Many devices and locations, one tenant. |
| **Record grain** | **Per-day.** One `attendance_record` per person per business date. Periods are a later add-on — the natural key is forward-compatible (§2.5) so adding them is data, not a migration. |
| **Jurisdiction** | **Philippines / non-EU.** RA 10173 (Data Privacy Act) is the governing law. EU support is a backlog item, not v1 (§7.4). |
| v1 features | Passive liveness · shifts & late detection · multi-device/location · notifications. |
| Admin config | Branding, kiosk text, attendance rules as settings rows, live-applied without redeploy. |
| **Client** | **Installable PWA** — phones (add to home screen) and wall-mounted tablets run the same bundle. No app stores, no native wrapper. |
| **Device mobility** | **Roaming.** A phone moves between locations, so location is declared per **scan session**, never a fixed property of the device (§6.5). |
| **TLS** | **Real domain + Let's Encrypt via DNS-01**, resolving to the LAN IP. Not an internal CA — see §6.5. |

### Verified environment

Apple M5 Pro (arm64), macOS. `uv`, Node 26, bun, Docker 29.6.1. **Pin Python 3.13** (see §0).

---

## 0. Corrections from review

Revision 1 claims that were **refuted by primary sources**. Each is already fixed in the body of this document; this table exists so the change is auditable and so nobody reintroduces the original.

| # | Rev-1 claim | Verdict | Correction |
|---|---|---|---|
| 1 | MiniFASNet input is "BGR uint8→float32 with **no** normalization" | **REFUTED** | Reference uses `transforms.ToTensor()`, which divides by 255 and transposes HWC→CHW. True contract: **BGR, CHW, float32 scaled to [0,1]**, no mean/std. Feeding 0–255 saturates the net and flattens the softmax — this would have silently broken spoof detection. |
| 2 | Client sends bbox "expanded 2.0×" | **REFUTED** | `parse_model_name` reads the crop scale from the filename: `2.7_80x80_MiniFASNetV2` → **2.7×**, `4_0_0_80x80_MiniFASNetV1SE` → **4.0×**. Two different crops are required. Client sends a **≥4.0× region plus bbox coords**; the server cuts both crops. |
| 3 | "Verify the live class index empirically" | Confirmed, and answered | `test.py`: `label == 1` → real face. **Index 1 = live.** Also: the two softmaxes are **summed then divided by 2**, not averaged pairwise. Keep a startup assertion anyway. |
| 4 | ARQ is the job runner | **REFUTED as forward-looking** | ARQ is **maintenance-only** (python-arq/arq#510, Oct 2025 — "no time to put significant effort into arq"). Still releases and supports 3.14, so shipping on it is fine. **Put it behind a `JobQueue` protocol**; `taskiq` is the escape hatch (but is still alpha-classified and moves cron to a separate package, so it is not a free upgrade). |
| 5 | Pin Python 3.12.13 because opencv/onnx wheels don't exist higher | **REFUTED** | 3.12 is now security-only. `opencv-python` 5.0 ships one `cp37-abi3` wheel covering 3.7–3.14; `onnxruntime` 1.28 ships arm64 wheels for cp311–cp314. The stated rationale is false. **Pin 3.13** (bugfix through 2029, full wheel coverage). |
| 6 | Vite 6 | **REFUTED** | **Vite 8** (Mar 2026, Rolldown). React 19 and Tailwind 4 are current. |
| 7 | ONNX Model Zoo ArcFace ResNet100 is the permissive fallback | **Partially refuted** | License **is** Apache-2.0 (correct). But the repo is archived and LFS downloads ended 1 Jul 2025 — fetch from Hugging Face. And it is materially weaker: **CFP-FP 94.21 vs buffalo_l's 99.20**. CFP-FP is the frontal-vs-profile benchmark, which is exactly the off-angle kiosk approach. Treat as fallback, not peer. |
| 8 | WeasyPrint needs Pango **and Cairo** | Partially refuted | v69 needs **Pango only**; rendering goes through `pydyf`. Container requirement (Pango + fonts) still holds. |
| 9 | Match threshold 0.45 | Refined | InsightFace's own guidance puts **0.30–0.45 as the 1:1 band** at FMR 1e-4…1e-5. Since 1:N needs more, expect the swept value to land **above** 0.45 (0.45–0.55). The `evaluate.py` sweep is blocking, not advisory. |
| 10 | Server pipeline 50–90 ms | At risk | Practitioner reports put a full buffalo_l pipeline at **100–200 ms on modern laptop CPUs**. Treat int8 `w600k_r50` and reduced `det_size` as **expected**, not fallback. Note `intra_op_num_threads=1` (pinned for test determinism) makes this worse — use different thread settings in production. |
| 11 | BIPA is "the highest-dollar risk" | Overstated | Illinois SB 2979 (Aug 2024) made repeated collection by the same method a **single violation**, killing the per-scan damages theory; the 7th Circuit held it **retroactive** in Apr 2026. All controls still required; exposure shrank. |
| 12 | *(not covered in rev 1)* | **New** | EU: consent is **not** a valid lawful basis for school attendance biometrics — the Swedish DPA's first-ever GDPR fine was this exact use case (power imbalance + proportionality), and the Italian SA fined a school for staff biometric attendance in 2025. EU AI Act applies fully **2 Aug 2026**; Art. 5(1)(f) **prohibits emotion inference in workplaces and schools**. See §7.4. |

Architecture defects found in review are corrected in §3–§5 and flagged inline as **[FIX-n]**.

---

## 1. Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python 3.13** + FastAPI + Pydantic v2 + uvicorn | Face engine is Python and sits on the latency path; any other API language adds an IPC hop and a second image serialization per scan. |
| ORM | SQLAlchemy 2.0 async (asyncpg) + Alembic | |
| DB | **Postgres 17, no pgvector** | **[FIX-D4]** pgvector was carried for analytics and duplicate detection, but embeddings are AES-GCM encrypted and therefore opaque to pgvector operators — it would have been an extension and a non-default image doing nothing reachable. Duplicate detection runs in the NumPy index that already exists. |
| Vector search | In-process NumPy brute force | 25k × 512 × f32 = 51 MB; one BLAS `sgemv`. Exact by construction — ANN recall misses concentrate at the decision boundary, where a silent false-reject is undebuggable in the field. Also the only option compatible with encrypted embeddings. |
| Cache / locks | Redis 7, **two logical roles** | **[FIX-B5]** `volatile-ttl` cache for cooldowns/rate-limits/settings; `noeviction` + AOF store for jobs and admin sessions. Neither Redis default is acceptable: `noeviction` makes `SET NX EX` fail on the scan path under queue pressure; `allkeys-lru` silently evicts cooldowns (double-punches) and sessions (mass logout mid-shift). |
| Jobs | ARQ **behind a `JobQueue` protocol** | Maintenance-only upstream (§0 #4). Same hedge as `FaceEngine`. |
| Frontend | React 19 + TS + **Vite 8**, TanStack Router/Query, Tailwind 4 + shadcn/ui | Two bundles: `apps/kiosk`, `apps/admin`. Kiosk must not ship admin JS. |
| Client gating | `@mediapipe/tasks-vision` (v1.0.0, Jul 2026) BlazeFace, **vendored not CDN** | Kiosk must work offline. Per-frame cost is unverified — measure it. |
| Export | `xlsxwriter` (`constant_memory=True`), WeasyPrint 69 (Pango only) | |

Repo: `/backend` (uv) · `/frontend` (bun workspaces) · `/models` (vendored ONNX) · `/infra` · `/docs`

---

## 2. Contracts — write these BEFORE any parallel work

The review's central finding on token efficiency: **every tunable in revision 1 was stated once, in prose, inside a table cell, with no key name.** Three agents would produce `face.match.threshold`, `matching_threshold`, and `MATCH_THRESHOLD`, and the settings, matcher, and admin-UI agents would not agree.

Everything in this section is a specification to **copy verbatim**, not a description to interpret. These land in Phase 0.5, which blocks all parallel work.

### 2.1 `SETTINGS_SCHEMA`

`backend/app/settings/registry.py`. Drives server-side validation *and* admin-UI generation. Scope column: `O`=org, `L`=location, `D`=device. Resolution is `D > L > O > code default`.

| Key | Type | Default | Range | Scope |
|---|---|---|---|---|
| `face.match_threshold` | float | `0.45` | 0.20–0.80 | O |
| `face.match_margin` | float | `0.05` | 0.0–0.30 | O |
| `face.low_confidence_threshold` | float | `0.38` | 0.20–0.80 | O |
| `face.low_confidence_action` | enum | `reject` | `reject`\|`confirm` | O·L |
| `face.det_score_min` | float | `0.60` | 0.10–0.99 | O |
| `face.det_size` | int | `384` | 128–800 | O |
| `liveness.mode` | enum | `monitor` | `off`\|`monitor`\|`enforce` | O·L·D |
| `liveness.threshold` | float | `0.75` | 0.0–1.0 | O |
| `scan.cooldown_seconds` | int | `60` | 0–3600 | O·L |
| `scan.cooldown_scope` | enum | `location` | `device`\|`location`\|`global` | O |
| `scan.duplicate_window_seconds` | int | `300` | 0–3600 | O |
| `scan.rate_per_second` | int | `2` | 1–20 | O·D |
| `scan.unknown_rate_per_minute` | int | `10` | 1–120 | O·D |
| `scan.unknown_lockout_seconds` | int | `60` | 0–3600 | O·D |
| `scan.min_inter_location_seconds` | int | `120` | 0–7200 | O |
| `scan.max_offline_backdate_minutes` | int | `240` | 0–1440 | O |
| `session.require_operator` | bool | `true` | roaming devices | O |
| `session.max_duration_minutes` | int | `240` | 5–1440 | O·L |
| `session.idle_timeout_minutes` | int | `20` | 1–240 | O·L |
| `session.require_geofence` | bool | `false` | | O·L |
| `session.geofence_radius_m` | int | `150` | 25–5000 | O·L |
| `kiosk.camera_facing` | enum | `user` | `user`\|`environment` | O·D |
| `kiosk.scan_mode` | enum | `continuous` | `continuous`\|`tap_to_scan` | O·L·D |
| `kiosk.low_battery_pct` | int | `15` | 0–50 | O |
| `kiosk.gate.min_bbox_area_pct` | float | `8.0` | 1–50 | O·D |
| `kiosk.gate.min_interocular_px` | int | `90` | 30–300 | O·D |
| `kiosk.gate.max_center_offset_pct` | float | `20.0` | 5–50 | O·D |
| `kiosk.gate.min_sharpness` | float | `60.0` | 0–1000 | O·D |
| `kiosk.gate.luma_min` / `luma_max` | int | `40` / `220` | 0–255 | O·D |
| `kiosk.gate.stability_iou` | float | `0.90` | 0.5–1.0 | O |
| `kiosk.gate.stability_frames` | int | `3` | 1–10 | O |
| `kiosk.gate.stability_ms` | int | `120` | 0–2000 | O |
| `kiosk.submit_throttle_ms` | int | `400` | 100–5000 | O·D |
| `kiosk.burst_count` | int | `2` | 1–5 | O |
| `kiosk.burst_interval_ms` | int | `150` | 50–1000 | O |
| `kiosk.crop_expand` | float | `4.0` | 2.0–6.0 | O |
| `kiosk.greeting_text` | str | `"Welcome"` | ≤120 chars | O·L·D |
| `kiosk.locale` | str | `"en"` | BCP-47 | O·L·D |
| `kiosk.result_duration_ms` | int | `3000` | 500–15000 | O·L·D |
| `kiosk.sound_enabled` / `show_photo` | bool | `true` / `true` | | O·L·D |
| `branding.org_name` | str | `""` | ≤120 | O |
| `branding.logo_asset_id` | uuid? | `null` | | O·L |
| `branding.primary_color` / `accent_color` | str | `#5e6ad2` / `#4cb782` | hex | O·L |
| `attendance.grace_in_minutes` | int | `10` | 0–240 | O·L |
| `attendance.grace_out_minutes` | int | `10` | 0–240 | O·L |
| `attendance.absent_after_minutes` | int | `60` | 5–1440 | O·L |
| `attendance.min_dwell_minutes` | int | `5` | 0–480 | O·L |
| `attendance.pairing_strategy` | enum | `first_last` | `device_direction`\|`toggle`\|`first_last` | O·L |
| `attendance.day_boundary_hour` | int | `0` | 0–23 | O·L |
| `attendance.auto_close_enabled` | bool | `false` | | O·L |
| `attendance.absence_notify_delay_minutes` | int | `10` | 0–240 | O |
| `privacy.region` | enum | `PH` | `PH`\|`US`\|`EU`\|`OTHER` | O |
| `privacy.store_enrollment_originals` | bool | `true` | | O |
| `privacy.store_failed_scans` | bool | **`false`** | | O |
| `privacy.debug_capture_mode` | bool | `false` | auto-expires 24h | O·D |
| `retention.embeddings_days_after_inactive` | int | `1095` | 30–3650 | O |
| `retention.enrollment_images_days` | int | `1095` | 30–3650 | O |
| `retention.unknown_face_hours` | int | `72` | 1–720 | O |
| `retention.events_days` / `records_days` / `audit_days` | int | `2555` | 365–3650 | O |

### 2.2 `FaceEngine` Protocol

`backend/app/face/protocol.py`. Images are **BGR uint8 HWC** throughout — never RGB, never float, at any boundary.

```python
Bbox = tuple[int, int, int, int]          # x1, y1, x2, y2
Landmarks = np.ndarray                     # (5, 2) float32

@dataclass(frozen=True)
class Detection:
    bbox: Bbox; det_score: float; landmarks: Landmarks
    blur_var: float; brightness: float

@dataclass(frozen=True)
class LivenessResult:
    live_score: float                      # combined[1] after summing both softmaxes / 2
    per_model: tuple[float, ...]
    passed: bool                           # live_score >= liveness.threshold

@dataclass(frozen=True)
class Embedding:
    vector: np.ndarray                     # (512,) float32, L2-normalized
    model_name: str; model_version: str

class FaceEngine(Protocol):
    def detect(self, bgr: np.ndarray) -> list[Detection]: ...
    def align(self, bgr: np.ndarray, lm: Landmarks) -> np.ndarray: ...   # -> (112,112,3) BGR
    def liveness(self, bgr: np.ndarray, bbox: Bbox) -> LivenessResult: ...
    def embed(self, aligned: np.ndarray) -> Embedding: ...
    @property
    def model_version(self) -> str: ...

class FakeFaceEngine(FaceEngine):
    def next_result(self, *, person: str | None = None, score: float = 0.9,
                    liveness: float = 0.95, n_faces: int = 1,
                    det_score: float = 0.9) -> None: ...
    def queue_results(self, results: list[dict]) -> None: ...
    def reset(self) -> None: ...
```

**MiniFASNet preprocessing, exact** *(§0 #1, #2, #3)*: for each model, crop the bbox expanded by that model's filename scale (2.7 and 4.0), `cv2.resize` to 80×80, keep **BGR**, transpose HWC→CHW, `astype(float32) / 255.0`, no mean/std. Sum the two 3-class softmaxes, divide by 2, take **index 1** as `live_score`. Assert the class index at startup against a bundled known-live and known-spoof fixture.

### 2.3 Kiosk WebSocket contract

`backend/app/api/schemas/kiosk.py` is the **single source**; TypeScript is **generated** from it into `frontend/packages/protocol/` via `make protocol` — never hand-maintained in two places.

```
client → server
  hello        { device_token_jwt, app_version, camera_label }
  heartbeat    { fps, queue_depth, error_count, clock_skew_ms }
  frame_burst  { idempotency_key, burst_seq, frames: [{ jpeg_b64, bbox,
                 monotonic_offset_ms }], gate_metrics }
server → client
  ready        { gallery_version, settings_version }
  detected     { }                                  # progressive feedback
  checking     { }
  result       { status, person?: {id, display_name, photo_url?},
                 direction, occurred_at, record_status, committed: true }
  settings_push{ settings_version, payload }
  backpressure { retry_after_ms }
  error        { code, message, details? }
```

`monotonic_offset_ms` is `performance.now()` elapsed since capture — **never an absolute client timestamp** *(§3.2)*.

**2-frame burst truth table** *(the review found this undefined)*:

| Frame A | Frame B | Result |
|---|---|---|
| accept(P) | accept(P) | **accept P** — use higher score |
| accept(P) | accept(Q≠P) | **ambiguous** |
| accept(P) | ambiguous / low-conf | **accept P** |
| accept(P) | no face | **accept P** |
| any | liveness fail (enforce) | **denied_spoof** — a spoof in either frame denies |
| both no face | | `NO_FACE` |

### 2.4 Error taxonomy

`backend/app/errors.py`. Envelope: `{"error": {"code", "message", "details"?}}`. Codes are **stable strings the kiosk switches on** to select localized copy.

| Code | HTTP | Kiosk copy (en) |
|---|---|---|
| `NO_FACE` | 422 | "Step into view" |
| `MULTIPLE_FACES` | 422 | "One person at a time" |
| `FACE_TOO_SMALL` | 422 | "Move closer" |
| `LOW_QUALITY` | 422 | "Hold still" |
| `LIVENESS_FAILED` | 403 | "Unable to verify — see an administrator" |
| `AMBIGUOUS` | 409 | "Try again" |
| `LOW_CONFIDENCE` | 409 | "Try again or use your PIN" |
| `UNKNOWN_FACE` | 404 | "Not recognized — use your PIN" |
| `COOLDOWN_ACTIVE` | 200 | "Already recorded at {time}" |
| `RATE_LIMITED` | 429 | "Please wait" |
| `LOCATION_CONFLICT` | 409 | "Recorded — flagged for review" |
| `DEVICE_REVOKED` | 401 | "This device needs re-pairing" |
| `SCAN_BACKEND_UNAVAILABLE` | 503 | "Temporarily unavailable — try again" |
| `NO_CONSENT` | 422 | *(admin-only)* |
| `DUPLICATE_ENROLLMENT` | 409 | *(admin-only)* |

### 2.5 Natural keys and DDL invariants

| Table | Natural key | Notes |
|---|---|---|
| `attendance_events` | `idempotency_key` unique | bigint identity PK. Append-only; corrections are new rows with `supersedes_event_id`. |
| `expected_attendance` | `(person_id, business_date, shift_id, period_label)` | `period_label` **NOT NULL, default `''`** — per-day today, per-period later without a migration. |
| `attendance_records` | `(person_id, business_date, shift_id, period_label)` | Same shape. **Per-day: `period_label = ''`.** Rebuildable cache. |
| `attendance_overrides` | `(person_id, business_date, shift_id, period_label)` | **[FIX-A3]** New table — see below. |
| `face_embeddings` | — | `(person_id) WHERE is_active`; `(model_name, model_version)`. |
| `settings` | `(key, scope, scope_id)` | |

**[FIX-A3] Overrides move out of `attendance_records`.** Revision 1 said records must be "fully reconstructible from events + expected + **overrides**" while storing overrides as a column *on* `attendance_records` — the reconstruction input was a subset of the output. That is circular, and it means the cache property could never actually be tested. Overrides now live in their own table with actor and reason, so `attendance_records` is genuinely disposable and the Phase 5 acceptance test becomes literally *truncate and rebuild, assert identical including overrides*.

### 2.6 Classification decision table

Ordered, **first match wins**. Implementation iterates this table; the Phase 5 suite iterates the same rows. `S`/`E` = expected start/end, `Gi`/`Go` = grace in/out, `A` = `absent_after_minutes`.

| # | Condition | Status |
|---|---|---|
| 1 | an `attendance_overrides` row exists | *(its status)* |
| 2 | `person_exceptions` covers the date | `excused` |
| 3 | `calendar_days` non-working, or rule `is_working_day = false` | `holiday` / `not_scheduled` |
| 4 | no expected row, events exist | `present_unscheduled` |
| 5 | no IN **and** `as_of < S + A` | **`pending`** *(new — see [FIX-A2])* |
| 6 | no IN **and** `as_of >= S + A` | `absent` |
| 7 | first IN `<= S + Gi` | `on_time` |
| 8 | first IN `<= S + A` | `late`, `late_minutes = in − (S + Gi)` |
| 9 | IN, no OUT, `as_of > E + auto_close` | `incomplete` |
| 10 | otherwise | `on_time` / `complete` |

Independently of `status`, set flags `was_late`, `left_early`, `location_mismatch`, `was_backdated`, `auto_closed`. `late` and `early_out` are not mutually exclusive, so reports count flags, not status.

### 2.7 Conventions that prevent agent collisions

- **Migrations: no issue labelled `parallel-safe` may author an Alembic revision.** N agents branching off the same `down_revision` produces N heads and a conflict on every one. One owner serializes the chain.
- **Co-owned files** structurally violate the non-overlapping-paths invariant and each need a named owner or an append-only rule: `conftest.py`, `SETTINGS_SCHEMA`, the Alembic chain, generated protocol types, the router registry.
- **Ownership is machine-checked**: `docs/ownership.toml` maps issue key → globs; CI asserts a change set is a subset of its issue's globs. Otherwise the invariant is honor-system between agents that never see each other.
- The committed `backend/app/**` skeleton tree lands in Phase 0.5 — ownership lines can only be non-overlapping if the layout is fixed first.

---

## 3. Scan pipeline

### 3.1 Client gate

Per frame on a 320×240 offscreen canvas, all thresholds from `kiosk.gate.*`: exactly one face → bbox area → inter-ocular distance → centering → variance-of-Laplacian sharpness (motion blur is the top cause of bad embeddings) → luma band → **stability: IoU ≥ 0.9 across 3 frames and ≥ 120 ms**. Then throttle, and hard-stop after a match until the face leaves frame.

On pass, send the bbox **expanded by `kiosk.crop_expand` (4.0)** plus the bbox coordinates, letterboxed to 480×480, JPEG q=0.85. *(§0 #2 — the server needs to cut both a 2.7× and a 4.0× crop, which a 2.0× region cannot supply.)*

### 3.2 [FIX-B1] Event timestamps

Revision 1 never said whether events carry the kiosk clock or the server clock. Both naive answers break something: server clock converts a 40-minute offline outage into a building full of `late` arrivals on replay (contradicting the plan's own offline feature); kiosk clock lets a wall tablet's settings screen backdate arrivals, which is attendance fraud defeating the entire FAR ≤ 0.1% effort.

Three fields, decided **before Phase 4** because the WS contract, the events DDL, and the resolver all encode it:

| Field | Meaning |
|---|---|
| `client_captured_at` | untrusted, recorded for diagnosis only |
| `server_received_at` | authoritative |
| `occurred_at` | `server_received_at − monotonic_offset_ms` for replayed events, else `= server_received_at` |

`monotonic_offset_ms` comes from `performance.now()`, immune to wall-clock tampering and NTP steps. Clamp to `scan.max_offline_backdate_minutes`, set `was_backdated`, surface in the Exception report. Heartbeat carries `clock_skew_ms`; drift shows on the device health strip.

### 3.3 Server pipeline

```
1. Auth / token bucket                    ~0.2 ms
2. JPEG decode                            ~2-4 ms
3. SCRFD detect  (face.det_size)          ~12-25 ms
4. 5-point align → 112×112 BGR            ~1 ms
5. LIVENESS (two crops, 2.7× and 4.0×)    ~4-8 ms   ← before recognition: cheaper, and a spoof must never touch the gallery
6. ArcFace embed → 512-d L2-normalized    ~25-40 ms
7. Gallery matmul → top-5 cosine          ~2-6 ms
8. Decision + Redis cooldown + impossible-travel
9. WRITE THE EVENT DURABLY                ~1-3 ms   ← [FIX-B3]
10. Respond; THEN enqueue resolve()
```

**[FIX-B3]** Revision 1 responded before writing. That is a lost-write window by construction: the kiosk has shown "Welcome, Maria" and will *not* replay from its offline queue — it received a success — so the person saw a record that does not exist, undetectably. One small INSERT against local Postgres is 1–3 ms out of a 220–380 ms budget. Only the `resolve()` enqueue is deferred.

**Latency expectation** *(§0 #10)*: budget for int8 `w600k_r50` and a reduced `det_size` as the **likely** configuration, not a fallback. Production thread settings differ from the test-pinned `intra_op_num_threads=1`.

### 3.4 Matching and limits

Bands per `face.*` settings: accept at `top1 ≥ threshold` **and** `top1 − top2_other_person ≥ margin`; ambiguous if the margin fails; low-confidence band; else unknown → PIN/QR. Log `top1_score` on every scan so the ROC can be re-derived from production data after 30 days and retuned without a redeploy.

**Threshold is set by the Phase 1 sweep, and that gate is blocking.** Expect it above 0.45 *(§0 #9)*. `evaluate.py` must report FAR **extrapolated to N=5000**, not raw at the ~100-identity eval size — the plan's own reasoning says FAR grows ~linearly with gallery size, so an un-extrapolated gate number is optimistic in the field.

**[FIX-B4] Impossible-travel check**, independent of cooldown. `cooldown_scope = location` by design lets one person clear both cooldowns at two sites in the same second — which puts them in two buildings on the **muster/fire roll**, a safety-critical report. One Redis key `scan:last:{person}` → `(location_id, ts)` set atomically with the cooldown; a different location within `scan.min_inter_location_seconds` emits `LOCATION_CONFLICT` and flags the event.

> **Roaming caveat.** This check assumes the reported location is trustworthy, which a roaming phone's is not — a stale session would flag every legitimate scan as fraud. Every event therefore carries **`location_source ∈ {device_fixed, session_declared, geofence}`**, and the check **only fires when both events have `location_source = device_fixed`**. Conflicts involving a roaming device are recorded as `location_unverified` on the Exception report rather than denied. See §6.5.

**Authority order** *(§0/[FIX-B5])*: the Redis cooldown is the **fast path**; the DB `idempotency_key` unique constraint plus a recent-event query is the **truth**. Revision 1 made attendance integrity a function of Redis memory pressure.

### 3.5 [FIX-B2] Gallery consistency

Redis pub/sub is **at-most-once** — a subscriber that is reconnecting, GC-paused, or booting misses the message permanently. Revision 1 used it as the *mechanism* for GDPR/RA-10173 erasure, meaning an erased person could still be recognized by a live process while the audit log asserted the erasure succeeded.

Pub/sub becomes an optimization, never the mechanism:

- Monotonic `gallery_version`, bumped **in the same transaction** as any embedding insert/delete/erase.
- The scan process polls it cheaply and reloads deltas when it lags; pub/sub just makes that 50 ms instead of N seconds.
- `/health/deep` exposes `gallery_version` and `index_loaded_version`, and **alarms on divergence** — revision 1 had no divergence detection at all.
- `POST /people/{id}/erase` returns success only after `index_loaded_version >= erasure_version`, else fails loudly.
- The same version-echo pattern applies to settings, so the "live in < 1 s" claim becomes verifiable.

---

## 4. Data model

Timestamps `timestamptz` UTC. UUID PKs except append tables (bigint identity). Hard delete on biometric tables.

**People** — `people` · `groups` (self-referencing `parent_group_id`) · `person_groups` **with `effective_from`/`effective_to`** (students change sections mid-year; last year's report must stay correct) · `guardians` / `person_guardians`.

**Biometrics** — `enrollment_assets` (encrypted originals, `capture_pose`, quality scores) · `face_embeddings` (`vector` bytea AES-GCM, `model_name`/`model_version`, `is_active`) · `consents` (type, granted_by self/guardian + relationship, method, `policy_version`, IP, revocation).

**Devices** — `locations` (**IANA `timezone` required**, plus `latitude`/`longitude` for optional geofencing) · `devices` (**`mode ∈ {fixed, roaming}`**, `location_id` **nullable when roaming**, direction, `token_hash` + prefix, pairing code, `allowed_cidrs`, `settings_override`, `form_factor`) · `device_heartbeats` (7 days; adds `battery_pct`, `clock_skew_ms`) · **`scan_sessions`** (§6.5).

**Scheduling** — `shifts` · `schedules` · `schedule_rules` · `schedule_assignments` (**person > group > location > org**, `priority` breaks ties) · `calendar_days` · `person_exceptions`.

**Attendance** — `attendance_events` (immutable) · `expected_attendance` (materialized) · `attendance_records` (derived cache) · **`attendance_overrides`** (new, §2.5).

**Config & ops** — `settings` · `admin_users` (argon2id, `scope_group_ids[]`, TOTP) · `admin_sessions` · `audit_log` (append-only, `prev_hash`/`hash` chain, **head exported off-box daily** — otherwise the chain only stops an attacker who cannot recompute it) · `notifications` (`dedupe_key` unique) · `notification_rules` · `report_jobs` · `assets`.

---

## 5. Attendance state machine

### 5.1 [FIX-A1] One writer

Revision 1 had two writers to `attendance_records` with no serialization. Concretely: the sweep fires at 08:45:00 and reads a snapshot; Maria scans at 08:45:01; the sweep commits `absent` at 08:45:02 from the stale snapshot; the debounced resolve writes `late` at 08:45:03. Best case every child arriving inside a sweep window gets an absence SMS then a retraction. Worst case — sweep commits last — Maria is `absent` **despite having scanned**, until the nightly sweep.

- **`mark_absences` never writes records.** It enqueues `resolve` jobs only. `resolve()` is the sole writer — this is a rule in `CLAUDE.md` alongside never-clobber-override.
- Do not rely on ARQ job-id dedup for the debounce: a scan arriving while a resolve is in flight can have its enqueue **refused as a duplicate**, silently dropping the scan's effect. Use a `dirty:{person}:{date}` flag that resolve re-checks at completion and re-enqueues itself if set.
- `resolved_as_of` column + conditional update, so an out-of-order job cannot overwrite a newer computation.
- Absence *notification* is delayed from absence *classification* by `attendance.absence_notify_delay_minutes`.

### 5.2 [FIX-A2] `resolve()` is pure only with `as_of`

The `absent` rule is a function of wall clock — the same (expected, events) inputs must give a different answer at 08:20 than at 08:50 — so revision 1's `resolve()` read a hidden global while claiming purity. And the status enum had no pending state, forcing the live board's "not-yet-arrived" tile onto a second code path that could disagree with the resolver.

```python
def resolve(person_id: UUID, business_date: date, *, as_of: datetime) -> None
```

Plus `pending` in the status enum (§2.6 row 5). The live board now reads records instead of reimplementing classification.

### 5.3 [FIX-A4] `business_date` belongs to the person, not the device

Revision 1 computed it in the **scanning** location's timezone, while `expected_attendance` was materialized in the person's **home** location timezone and boundary hour. A Manila-assigned person scanning in Singapore — or a US-Eastern employee at a Central site, or a home site with `day_boundary_hour = 04:00` visiting one with `00:00` — produces `present_unscheduled` at the visited site *and* `absent` at home, for one person, one day, one instant. Multi-building scanning is explicitly normal in this design.

- `attendance_events.business_date` is **NULL at write time** — the WS hot path does not know the schedule context; the resolver does.
- `device_local_date` is stored separately for device/ops reporting.
- The resolver matches events to expected rows by **absolute UTC interval containment**: `occurred_at ∈ [expected_start_at − lookback, expected_end_at + lookahead]`. This is already how overnight pairing works; extending it here deletes the whole bug class.
- `business_date` becomes a reporting label derived from the matched expected row.
- Unknown faces (`person_id IS NULL`) have no person timezone — they use the device location timezone.

Also: `expected_start_at` is materialized as an absolute timestamp up to 14 days out, so a tzdata update between expansion and the date silently invalidates it. Store local wall time + tz alongside the absolute, and re-derive on tzdata version change.

### 5.4 [FIX-A3] Retroactive schedule edits

Revision 1's `expand_schedules` "never touches past rows", so `recompute_range` — the stated escape hatch for "the schedule was wrong for three weeks" — re-derived records from frozen, wrong expected rows and converged on the same wrong answer. The escape hatch could not reach the layer holding the error. And allowing past re-expansion would delete expected rows that override rows key to, destroying "inviolable" overrides by cascade rather than by recomputation.

- `expand_schedules` gains an explicit `allow_past=True` backfill mode, invoked only by `recompute_range`.
- Expected rows referenced by a record or override are **soft-deleted/versioned**, never hard-deleted.
- Orphaned overrides surface in the Exception report; never silently dropped.
- Overrides live in their own table (§2.5), so the rebuild test is real.

### 5.5 [FIX-A5] Expansion cost

Revision 1 re-expanded the full 14-day × 5,000-person horizon on **any** schedule, calendar, or exception change. Importing next term's calendar (30 edits) meant 30 full DELETE+INSERT passes, bloating the table daily. Row volume itself is fine for Postgres; the trigger granularity is not.

- Derive the affected `(person set × date range)` from the changed entity; expand only that.
- Coalesce/debounce expansion per location.
- True `INSERT … ON CONFLICT DO UPDATE` on the natural key, so unchanged rows are no-ops.
- **`person_groups` changes must trigger re-expansion** — mid-year section moves are a first-class feature in §4 and revision 1 never wired them to expansion at all.

### 5.6 [FIX-B6] Duplicate people cause a permanent denial of service

Two person IDs for one human (SIS import under two external_ids, or enrollments predating the duplicate check) produce embeddings ~0.9 cosine to each other. The margin rule then evaluates to **ambiguous on every scan, forever** — that individual is told "try again" indefinitely, and the only trace is a log line. Revision 1's margin rule converted a data-quality problem into a total denial of service for one person.

- The ambiguity tray groups by **pair of person_ids** and offers "probably the same person → merge" as a first-class action.
- **Define person-merge**: the never-UPDATE-events rule forces a choice; use a `merged_into` pointer, leaving events immutable.
- Duplicate detection also runs as a **scheduled full-gallery job**, not only at enrollment commit.

### 5.7 Pairing

`device_direction` · `toggle` (with `min_dwell_minutes`) · **`first_last`, default** — first event of the day IN, last OUT. Pairing operates on the person's event stream across devices; IN at Building A / OUT at Building B is allowed but flagged `location_mismatch`.

---

## 6. Frontend, API, reports

API surface is unchanged from revision 1 except: `attendance/records` gains `?as_of=`, `/health/deep` exposes gallery and settings versions, and `POST /people/{id}/erase` blocks on index convergence.

**Kiosk** — gating loop, overlay states, result card, PIN/QR fallback always visible, IndexedDB offline queue with `idempotency_key` replay, Wake Lock, hidden diagnostics. All branding from `/kiosk/bootstrap`, live-pushed. **`getUserMedia` requires a secure context** — `localhost` is exempt, `http://192.168.1.50` is not, so every LAN kiosk needs a real cert (Caddy internal CA, Phase 4).

**Admin** — live board, device health strip, anomaly tray (spoof denials, unknown faces, ambiguous **grouped by person pair**), people/enrollment, devices, schema-driven settings with live kiosk preview and the FAR/FRR threshold curve, manual overrides.

**Reports** — daily register, timesheet, payroll summary, tardiness, absence, truancy, perfect attendance, headcount by hour, **muster/fire roll** (one click, renders from cache with a visible staleness indicator when the API is unreachable), exception report, device health. Renderers: CSV (streaming, **UTF-8 BOM** or Excel mangles accented names), XLSX (`constant_memory`, typed cells), PDF (WeasyPrint, **Pango only**). Exports >5,000 rows are async jobs with expiring signed URLs, and **every export writes an audit row**.

---

## 6.5 Mobile PWA and roaming devices

The client is an **installable PWA**. A phone and a wall-mounted tablet run the same bundle; "install" is the browser's add-to-home-screen prompt, giving an icon, splash screen, and fullscreen. No app stores, no native wrapper, no review process, and updates ship instantly.

### Scan sessions — location is declared, not assumed

A roaming phone breaks the assumption that a device's location is fixed and trustworthy. Location moves onto a **session**:

**`scan_sessions`** — `id`, `device_id`, `location_id`, `operator_admin_id` (nullable for fixed devices), `location_source` (`device_fixed|session_declared|geofence`), `started_at`, `ended_at`, `last_activity_at`, `start_lat`/`start_lng`/`gps_accuracy_m`, `scan_count`, `end_reason` (`explicit|idle_timeout|max_duration|token_revoked`).

- **Fixed devices** open an implicit permanent session at their assigned location — behaviour is unchanged from the current design.
- **Roaming devices** must open a session before scanning: pick a location, optionally confirm by geofence, and — when `session.require_operator` — authenticate a human. Every event carries `session_id` and `location_source`.
- Sessions auto-close on `session.idle_timeout_minutes` or `session.max_duration_minutes`, so a phone left in a bag does not keep attributing scans to a room nobody is in.

**Operator accountability is new.** A wall kiosk has no human behind it, so a device token was sufficient. A roaming phone is carried by someone, and "who took this attendance" is a question a school will ask. Roaming sessions therefore require both the **device token and an operator login**, and the operator lands on the event and in the audit log. This also gives the natural revocation story: a lost phone is revoked at the device *and* the operator's sessions are killed.

> **Tension worth naming.** Roaming phones make classroom attendance the obvious use case, and classroom attendance is inherently **per-period** — while the locked decision is per-day records. That decision stands, and the natural key `(person, date, shift, period_label)` already accommodates periods as data (§2.5). But expect the per-period case to arrive sooner than the plan assumes.

### What changes for a phone

| Concern | Handling |
|---|---|
| Camera | `facingMode` from `kiosk.camera_facing` (default front); explicit camera picker; handle orientation change without dropping the stream |
| Battery / thermal | Continuous camera on a phone drains fast and throttles. `kiosk.scan_mode = tap_to_scan` is the roaming default; stop the stream when the session is idle or the app is backgrounded; surface `battery_pct` on the device health strip and warn below `kiosk.low_battery_pct` |
| Offline | Far more important than for a wired kiosk — walking between buildings drops connectivity routinely. The IndexedDB queue and `monotonic_offset_ms` backdating (§3.2) are what make this correct, and they already exist |
| **iOS storage eviction** | Safari can evict PWA storage under pressure, which would silently drop queued offline scans. Request persistent storage, surface queue depth in the UI, and **warn the operator before a session ends with unsent events** |
| Screen | Responsive down to ~375 px; the kiosk result card is currently designed for a large mounted display |
| Wake Lock | Already planned; matters more on a phone that aggressively sleeps |

### TLS: real domain, not an internal CA

The revision-2 plan used Caddy with an internal CA. **That does not survive contact with phones.** Trusting a private root on iOS means installing a configuration profile *and* separately enabling full trust in Settings → General → About → Certificate Trust Settings — per device, repeated after every reset, on hardware the admin may not own. It is a recurring support burden that will be blamed on the app.

Instead: a **real domain with a Let's Encrypt certificate issued via the DNS-01 challenge**, with an A record pointing at the server's LAN IP. DNS-01 needs no inbound reachability, so the server stays entirely LAN-only while every phone trusts it with **zero configuration**. Caddy automates this natively with a DNS-provider plugin. The only requirements are a domain and API credentials for its DNS provider.

Fallback if a domain is genuinely unavailable: keep the internal CA, but scope it to devices the organization owns and provisions, and document the per-platform trust steps in the kiosk runbook.

---

## 7. Privacy & security

### 7.1 What is stored

Embeddings always. **Enrollment originals: yes, encrypted, consented** — ArcFace embeddings are model-version-locked, so without originals a model swap means re-enrolling everyone. **Scan frames: never by default**; failed-scan capture is opt-in with a 72 h TTL. **Never expose raw vectors over the API** — face embeddings are partially invertible.

### 7.2 [FIX-D2] Encryption threat model, stated honestly

Envelope encryption (AES-256-GCM, per-record DEK, KEK outside DB and backup) genuinely defends **an offline `pg_dump`, a stolen backup, or a lifted disk**. It does **not** defend a process holding 25,000 decrypted templates in RAM for its lifetime — and on a self-hosted box where app, DB, and KEK file often share a host, whoever reads process memory can usually read the KEK. The real adversary is *"obtains the database or backup but not the host."* Write that down rather than implying general protection.

Cheap hardening: `mlock` the gallery buffer or disable swap; `RLIMIT_CORE=0` and non-dumpable on the scan process; KEK on a separate mount.

**Replace the weak acceptance test.** `pg_dump | grep` would pass on base64 plaintext. The real test: **restore the dump on a machine without the KEK and prove the gallery cannot load.** Phase 9 must also verify the backup excludes the KEK.

### 7.3 [FIX-D1] The kiosk claim was false

Revision 1 said "a compromised kiosk yields nothing beyond what its screen already shows." The screen shows one person transiently; the *device* holds a persistent token in IndexedDB, the bootstrap payload, and — because rate limiting applied only to *unknown* faces and the successful-match path had no limiter — an uninterrupted stream of `(name, photo, timestamp, location)` for everyone who walks past, all day. That is a photographic roster plus a movement log, exfiltrated passively from a device on a public wall.

- Rewrite the claim honestly — a privacy reviewer will test that sentence.
- Decide whether the result card needs a **photo**; if so, send a short-TTL signed URL, not embedded bytes, so captured traffic expires.
- Distinct-identities-per-hour anomaly alert per device.
- `allowed_cidrs` **required and enforced at WS upgrade** — the column already existed and was never used.
- **Rotate the persistent device token on every heartbeat.** A copied token then dies at the next rotation, and two devices presenting the same generation is *detectable* → auto-revoke and alert. Token theft becomes noisy rather than silent.

### 7.4 Jurisdiction

**Philippines is the governing jurisdiction (RA 10173, Data Privacy Act of 2012).** Biometric data is **sensitive personal information** under §3(l), which means: processing generally requires **consent that is specific and informed** (§13), a **Data Protection Officer** must be designated, NPC **registration** applies to systems processing sensitive data of 1,000+ individuals — a 5,000-person deployment clears that bar — and the **Security of Sensitive Personal Information** rules (§20) require encryption. Breach notification to the NPC and affected individuals is required within **72 hours** of knowledge. The existing design (consent gate, encryption, retention job, audit log, erasure) satisfies these; the additions are a **named DPO field, an NPC registration checklist, and a 72-hour breach-notification runbook**.

**United States (BIPA)** — still build the written policy, retention schedule, written consent, and 3-year destruction. Exposure is materially lower than revision 1 implied (§0 #11).

**EU — explicitly out of scope for v1, tracked as backlog.** The findings are recorded so the decision is informed rather than accidental: consent is **not** a valid lawful basis for school attendance biometrics (Swedish DPA's first GDPR fine, on exactly this use case — power imbalance plus a proportionality failure, since attendance can be taken less intrusively; Italian SA fined a school for staff biometric attendance in 2025). EU AI Act applies fully **2 Aug 2026**, and **Art. 5(1)(f) prohibits emotion inference in workplaces and educational institutions** — a hard "never build this" line regardless of jurisdiction.

Two hooks make the EU path additive rather than a rewrite, and both are cheap now:
1. `privacy.region` setting already exists (§2.1) and can hard-disable face capture.
2. The **PIN/QR fallback is built in Phase 4 regardless** — it is an accessibility requirement and what makes consent genuinely voluntary. An EU profile would promote it to primary and use the face only to *confirm* a claimed identity (1:1), which likely falls under the AI Act Recital 17 verification carve-out that 1:N gallery search does not.

### 7.5 Consent, retention, deletion

No embedding without an active `biometric_enrollment` consent at the current `policy_version`, enforced at DB and application layers. Retention per `retention.*` (§2.1), nightly, audited per batch. **Erasure**: hard-delete embeddings and assets, shred blobs, **block on index convergence** (§3.5), null PII, keep attendance history pseudonymized — it is payroll/regulatory data with an independent lawful basis. **DSAR export**: everything except raw embeddings; disclose their count and model version in a manifest.

---

## 8. [FIX-D3] Scan topology — decide in Phase 0.5, not Phase 4

Revision 1 stated the conclusion ("a single dedicated scan process with the model-free API on separate workers") while filing it as a Phase 4 decision informed by a Phase 10 load test. But the memory arithmetic (N workers × 3 ONNX models × ~600 MB) is knowable on day one, and it is a **process-boundary** decision — it determines whether the WS endpoint calls the engine in-process or across an IPC hop. That endpoint is the first Phase 4 issue and everything else in Phase 4 blocks on it, so deciding afterwards means rebuilding it.

Availability was entirely unaddressed. Restart cost is three model loads plus a 51 MB decrypt-and-load; with one process and no standby, **every deploy or OOM is a site-wide outage** — and the only twenty minutes that matter at a school are the morning rush.

- **Two scan processes** behind a shared queue from the start. They are stateless given the gallery; ~1.2 GB is nothing on the target hardware.
- Rolling restart with readiness gated on `index_loaded_version`.
- Kiosk behaviour on unavailability is specified, not left to an agent: return `SCAN_BACKEND_UNAVAILABLE` in < 500 ms and show "try again". **Never hang on a spinner, and never enqueue to the offline queue** — an unprocessed face is not a deferred event.

---

## 9. Testing

`FaceEngine` is a Protocol and ~95% of the suite runs against `FakeFaceEngine` (§2.2), so everything but the model is ordinary deterministic software.

- **L1** — matcher bands, cosine math, `business_date`, schedule resolution, the whole classifier. `hypothesis` properties: a normalized vector scores 1.0 against itself; adding an embedding never lowers that person's best score; **`resolve()` is idempotent for a fixed `as_of`**; classification is monotonic in arrival time.
- **L2** — pipeline and API against the fake: cooldowns, limits, liveness branching, ambiguity, unknown-face lockout, WS protocol, event writing, resolution, notifications — zero images, perfect determinism.
- **L3** — `@pytest.mark.models`, nightly. Embedding stability against checked-in golden `.npy` within `atol=1e-3` (catches onnxruntime upgrades and preprocessing drift, the failures that silently degrade accuracy without throwing). Accuracy regression `TAR@FAR=1e-3 ≥ baseline − 0.01`. **Liveness class-index assertion** (§2.2).

**Fixtures:** synthetic 512-d vectors with controlled intra/inter-class structure for L1/L2 — the matcher needs no pixels. For L3, ~50–100 rights-cleared or synthetic images **outside the repo**; do not vendor LFW/CelebA/VGGFace2 (research-use-only or withdrawn, and checking real faces into a biometrics repo is what this app's own policy forbids).

**Initial tester.** The project owner supplies the first real face images and acts as tester zero. This unblocks the Phase 1 smoke path immediately — enroll, probe, confirm a match, confirm liveness separates a real face from a photo of it on a screen — long before the ~100-identity eval set exists.

Handling is not optional, because these are a real person's biometrics under the same rules the app enforces on its users:
- Images live in `fixtures/faces/`, which is **gitignored**. Only the derived **golden `.npy` embedding** is committed — it is the actual test assertion, it is tiny, and a stored vector is never re-derivable into a repo-visible face.
- Never attach a face image to a Linear issue, a PR, or a log.
- The owner can revoke at any time: delete the directory and regenerate goldens from a replacement.

**This does not substitute for the eval set.** One identity cannot produce a FAR/FRR curve — impostor rates need many identities. Tester zero proves the pipeline runs end to end; TEN-18 still needs ≥100 identities to set the threshold, and TEN-89 still needs ~20 volunteers to measure field accuracy.

**Determinism traps:** assert on `.npy`, never re-decoded JPEG; pin one resize path (`cv2` ≠ `PIL` at the same nominal interpolation); `intra_op_num_threads=1` in tests only; `time-machine` with **at least one non-UTC location timezone** — a UTC-only suite will not catch timezone bugs.

**E2E:** Chromium `--use-fake-device-for-media-capture --use-file-for-fake-video-capture=fixtures/alice.y4m`. Y4M only, uncompressed, Chromium-only; the file is re-read continuously so swapping it mid-test switches the feed.

**Load:** 20 kiosks × 1 scan/3 s against a 5,000-person gallery; p95 < 500 ms, **no cooldown leakage across workers**.

---

## 10. Phases

| # | Phase | Done when |
|---|---|---|
| 0 | **Scaffold** — uv @ **3.13**, compose (PG17 **no pgvector**, Redis with both policies), Caddy, toolchain, bun workspace | `docker compose up` reaches PG + Redis; `uvicorn` serves `/health` |
| **0.5** | **CONTRACTS — blocks all parallel work.** Everything in §2: `SETTINGS_SCHEMA`, `FaceEngine` Protocol + `FakeFaceEngine`, WS contract with generated TS, error taxonomy, natural keys, classification decision table, skeleton tree, `docs/ownership.toml` + CI check, migration-ownership rule, shared fixture factories. **Plus the §8 topology decision.** | `make protocol` regenerates TS with no diff; the ownership CI check fails on a deliberate violation; two agents given adjacent issues have zero path overlap |
| 1 | **Face engine spike (CLI only)** + **hallway test** | Latency, ROC at FAR ≤ 0.1% **extrapolated to N=5000**, liveness separating real/print/replay — **and** the hallway test below |
| 2 | Data model, migrations, core API, auth, audit, consent | Migrations up/down clean; every mutation audited; RBAC proven at the repository layer |
| 3 | Enrollment + gallery index (with versioned consistency, §3.5) | 20 people enrolled; index loads < 2 s; duplicate blocked; no-consent → 422; **index divergence alarms** |
| 4 | Kiosk scan loop, device auth, PIN/QR, offline queue, TLS | < 500 ms p95 on LAN; printed photo denied; 30 s outage replays to exactly N records **with correct backdated timestamps** |
| 5 | Schedules + state machine | ≥40 cases incl. both DST transitions and overnight; **truncate `attendance_records` and rebuild → identical, overrides intact** |
| 6 | Admin dashboard + configurable UI | Branding change reaches a running kiosk in < 2 s, no redeploy |
| 7 | Reports & export | 50k-row CSV under 200 MB RSS; every export audited |
| 8 | Notifications | Exactly one guardian message per absence; retraction on late arrival; outage retries never double-send |
| 9 | Privacy & hardening **+ model-swap path** | **Restore on a KEK-less machine → gallery cannot load**; erasure clears DB, disk, and live index; audit chain verifies and its head is exported off-box |
| 10 | Packaging & ops | Clean machine → working kiosk in < 30 min from the runbook alone |

### [FIX-E] Add a hallway test to Phase 1

The Phase 1 gate as written proves latency and ROC on curated images — the *least* likely thing to fail on an M5 with good input. The risks that actually kill this project are enrollment quality from real admin captures, backlit doorway lighting, and a client gate tuned so tightly nobody gets through. None of those surface before Phase 4, and throughput not until Phase 10.

**Half a day, before sign-off:** a laptop webcam at the real mounting height in the real lighting, ~20 volunteers enrolled through the intended 5-pose flow, ~200 walk-up probes, measuring in-situ FRR and time-to-recognition. No UI, no DB, no WS — the existing CLI in a loop. That falsifies "people in this building can be recognized reliably" weeks before any UI exists. Concurrency can stay in Phase 10; it is an engineering problem with a known fix (§8). Field accuracy is the one with no fix.

### [FIX-D5] Model-swap path is now a Phase 9 deliverable

Retaining encrypted originals is justified entirely by "swapping the model is a background job" — yet that job appeared in no phase in revision 1, while `buffalo_l` licensing was named the #1 risk. The mitigation for the top risk was the least-specified thing in the plan. Needs: `model_version` partitioning on the index, a dual-index read path during migration, the re-embed job, and an upgrade runbook covering migration + model version + re-embed ordering.

### Cut or deferred

- **pgvector** — cut (§1).
- **Device-scope settings overrides** — deferred. Four-level resolution plus per-device JSONB plus a schema-driven generator plus live preview is a lot of Phase 6 for one organization; `org > code default` plus a small device allowlist covers nearly all real cases.
- **Second liveness model on the hot path** — run one in v1 while shipping at `monitor`; keep the second behind the Protocol.

---

## 11. Critical files

| Path | Role |
|---|---|
| `backend/app/settings/registry.py` | `SETTINGS_SCHEMA` (§2.1) — highest-leverage artifact; six phases read it |
| `backend/app/face/protocol.py` | `FaceEngine` + `FakeFaceEngine` (§2.2) |
| `backend/app/face/liveness.py` | MiniFASNet — **the corrected preprocessing (§0 #1–3)** |
| `backend/app/face/gallery.py` | NumPy index, matcher, versioned consistency (§3.5) |
| `backend/app/api/schemas/kiosk.py` | WS contract, source of generated TS (§2.3) |
| `backend/app/errors.py` | Error taxonomy (§2.4) |
| `backend/app/models/attendance.py` | events / expected / records / **overrides** (§2.5) |
| `backend/app/attendance/resolver.py` | `resolve(..., as_of)` — sole writer (§5.1–5.3) |
| `backend/app/api/ws_kiosk.py` | Latency-critical path |
| `frontend/apps/kiosk/src/scan/useScanLoop.ts` | Gating, stability gate, throttle, WS client |
| `docs/ownership.toml` | Issue → path globs, CI-enforced (§2.7) |
| `models/checksums.txt` | Vendored ONNX; never fetch at runtime |

---

## 12. Verification

**Phase 0.5 gate:** `make protocol` regenerates TypeScript with no diff; the ownership CI check fails on a deliberate cross-boundary edit; `SETTINGS_SCHEMA` round-trips through the resolver at all three scopes.

**Phase 1 gate (blocking):**
```bash
uv run python -m app.face.bench    --iterations 100
uv run python -m app.face.evaluate --enroll fixtures/enroll --probe fixtures/probe --extrapolate-to 5000
uv run python -m app.face.liveness_check --live fixtures/live --spoof fixtures/spoof
```
Plus the hallway test results in `docs/phase1-results.md`, and the `buffalo_l` vs Apache-2.0 accuracy delta recorded (expect a large CFP-FP gap, §0 #7).

**Per phase:** `make check` = ruff + mypy --strict + pytest + migration up/down round-trip. `pytest -m models` nightly.

**End-to-end, from Phase 4** — additions to revision 1 in bold:
1. `docker compose up`, `make seed`
2. Enroll through all three paths
3. Scan from a second device over `https://` on LAN — identity < 500 ms, record on the live board
4. Printed photo and phone screen both denied in enforce mode
5. Branding change → running kiosk updates in < 2 s
6. `attendance.grace_in_minutes` change → new scan reclassifies
7. Network out 30 s, scan 3× → exactly 3 records, **timestamps backdated to capture time, not reconnect time**
8. **Scan the same person at two locations within 10 s → `LOCATION_CONFLICT`, muster shows one location**
9. **Kill a scan process mid-burst → kiosk shows "try again" in < 500 ms, no phantom record**
10. **Truncate `attendance_records`, run `recompute_range` over a month → identical, manual overrides intact**
11. Export the daily register to CSV/XLSX/PDF; audit row per export
12. `POST /people/{id}/erase` → **blocks until the live index converges**; history survives pseudonymized
13. **Restore a backup on a machine without the KEK → the gallery cannot load**

Playwright E2E (fake Y4M camera) and the k6 load scenario run before each release.
