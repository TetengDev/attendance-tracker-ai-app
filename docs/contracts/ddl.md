# DDL contract — natural keys and migration conventions

This contract is the Phase 0.5 source for data-model grain, natural keys, and
migration ownership. It mirrors `docs/PLAN.md` revision 2 §2.5 and prevents
parallel agents from inventing incompatible table grains.

## Natural keys

| Table | Natural key | Required invariants |
|---|---|---|
| `attendance_events` | `idempotency_key` unique | Bigint identity PK. Append-only. Corrections are new rows with `supersedes_event_id`; never update/delete events. |
| `expected_attendance` | `(person_id, business_date, shift_id, period_label)` | `period_label NOT NULL DEFAULT ''`. Rows referenced by records or overrides are soft-deleted/versioned, not hard-deleted. |
| `attendance_records` | `(person_id, business_date, shift_id, period_label)` | Same shape as expected rows. Per-day v1 uses `period_label = ''`. Derived cache; disposable and rebuildable. |
| `attendance_overrides` | `(person_id, business_date, shift_id, period_label)` | Separate from `attendance_records`; includes actor and reason. Rebuilds must preserve override effects without clobbering override rows. |
| `face_embeddings` | no business natural key | At most one active embedding per person per model release: partial unique `(person_id, model_name, model_version) WHERE is_active`. Raw vectors are encrypted `bytea`. |
| `settings` | `(key, scope, scope_id)` | Scope resolution is `device > location > org > code default`; key must exist in `SETTINGS_SCHEMA`. |

## Attendance grain

The v1 record grain is per day. The forward-compatible key shape is:

```text
(person_id, business_date, shift_id, period_label)
```

`period_label` is required and defaults to the empty string. Do not use nullable
period columns; `NULL` breaks equality and makes conflict targets ambiguous.
Adding per-period records later is data (`period_label = 'math-1'`), not a
schema migration.

## Attendance table split

Attendance uses four tables:

1. `attendance_events`: raw immutable facts.
2. `expected_attendance`: materialized schedule expectations.
3. `attendance_records`: rebuildable derived cache.
4. `attendance_overrides`: non-disposable human corrections.

`resolve(..., as_of=...)` is the sole writer to `attendance_records`.
`attendance_overrides` is never deleted by expected-row re-expansion and is
never overwritten by recomputation.

## Timestamp conventions

- Store absolute timestamps as `timestamptz` in UTC.
- Keep `client_captured_at`, `server_received_at`, and `occurred_at` distinct.
- `attendance_events.business_date` is null at write time; the resolver derives
  the business date from the matched expected row.
- `device_local_date` may be stored for operations/reporting, but it is not the
  attendance business date.

## Shared column conventions

Use the constants in `backend/app/db/base.py` rather than restating natural keys
or timestamp-column names in migrations or model modules.

## Migration ownership rule

No issue labelled `parallel-safe` may author an Alembic revision. Alembic
revisions are serialized by a designated migration owner because multiple agents
branching from the same `down_revision` produce multiple heads by construction.

Review checklist:

- If a PR contains `alembic/versions/**`, confirm its Linear issue is not
  labelled `parallel-safe`.
- Confirm the PR body names the owning Linear issue.
- Confirm the PR link is attached to the Linear issue before review.
