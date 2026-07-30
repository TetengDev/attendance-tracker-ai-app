# Scan process topology

This is the Phase 0.5 decision for `TEN-46`. It fixes the process boundary
before Phase 4 starts implementing the WebSocket scan endpoint.

## Decision

Run **two dedicated scan processes** behind a shared queue from the start. Keep
the model-free API on separate workers.

The WebSocket scan endpoint submits work to the scan runtime boundary; it does
not load ONNX models inside generic API workers and does not fork after model
load.

## Why this is fixed before Phase 4

The scan endpoint shape depends on this choice. If Phase 4 first builds an
in-process endpoint and later discovers that each API worker loads three ONNX
models, the endpoint has to be rebuilt around an IPC/queue boundary. The memory
math is knowable now:

```text
3 ONNX models × ~200 MB = ~600 MB per model-owning process
```

With generic `uvicorn --workers N`, that becomes `N × ~600 MB` plus thread
contention. Two dedicated scan processes cost roughly 1.2 GB on the target
hardware, keep the API workers model-free, and provide a standby during rolling
restart.

## Runtime topology

| Component | Count | Owns models? | Role |
|---|---:|---|---|
| API workers | 2+ | No | Auth, admin API, model-free kiosk bootstrap, WS upgrade, request routing |
| Scan processes | 2 | Yes | Detect → liveness → embed → match → decision |
| Shared queue | 1 logical queue | No | Backpressure boundary between API and scan processes |
| Redis/Postgres | shared | No | Cooldowns, settings/gallery versions, durable events |

The scan processes are stateless given the gallery and settings version. A
rolling restart drains one process while the other stays ready.

## Readiness

A scan process is ready only when:

1. all model sessions are loaded and warmed,
2. `gallery_version` has been read,
3. `index_loaded_version >= required_gallery_version`,
4. settings have been loaded at a known `settings_version`.

During deploy or startup, the API must return `SCAN_BACKEND_UNAVAILABLE` in
less than 500 ms when no scan process is ready. The importable contract encodes
this as a 499 ms upper deadline so tests cannot accidentally permit an exact
500 ms response. Do not leave the kiosk on an indefinite spinner, and do not
enqueue unprocessed faces to the offline queue; an unprocessed face is not a
deferred attendance event.

## Threading

Tests use deterministic ONNX settings (`intra_op_num_threads=1`). Production is
explicitly configured and may differ. Thread counts are runtime configuration,
not call-site constants; the runtime contract requires an explicit ONNX
threading policy before model code lands.

## Model loading invariant

Models are loaded once per scan process:

- never per request,
- never in generic API workers,
- never before forking worker processes.

The acceptance check for real implementations must prove model load count per
process and record RSS/p95 latency for at least:

1. generic API workers with model ownership,
2. the selected two-scan-process topology.

The recommendation remains two scan processes unless measurement shows a
strictly better topology without sacrificing rolling-restart availability.
