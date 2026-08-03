# Audit chain-head export

The audit log is tamper-evident only when its head is copied somewhere the app
runtime cannot rewrite. The database trigger blocks normal `UPDATE`/`DELETE`,
but an operator with full database access could still rewrite history and
recompute every row hash. A daily off-box head export gives reviewers a value to
compare against later.

## Export record

Each export is one JSON file with:

- `exported_at`
- `row_count`
- `last_id`
- `head_hash`
- `verified_head_hash`
- `source`
- `version`
- `environment`
- `deployment_id`

Before writing the file, the command verifies the persisted audit chain with
`verify_persisted_audit_chain()`. If verification fails or the verified head
does not match the latest row hash, the command exits non-zero and writes
nothing.

## Local run

Create an export directory outside the repository:

```bash
mkdir -p /tmp/attendance-audit-heads
AUDIT_CHAIN_EXPORT_DIR=/tmp/attendance-audit-heads make audit-chain-export
```

For production, `AUDIT_CHAIN_EXPORT_DIR` must be an absolute path outside the
application checkout and should be a mounted off-box or write-once destination.
Outside the repo is only a safety floor; it is not automatically off-box. Prefer
storage controlled by a different account or host, such as WORM storage,
append-only object storage, or a backup host where the application runtime cannot
overwrite or delete prior files.

Set `AUDIT_CHAIN_EXPORT_ENVIRONMENT` and `AUDIT_CHAIN_EXPORT_DEPLOYMENT_ID` so
export records can be traced across production, staging, restores, and appliance
replacements.

The command refuses relative paths and refuses paths inside the repository.

## Scheduling

Install the sample cron file from `infra/cron/audit-chain-export`, then edit:

- the checkout path, default `/opt/attendance-tracker-ai-app`
- `AUDIT_CHAIN_EXPORT_DIR`, default `/mnt/audit-chain-heads`

The cron entry runs daily at 02:17 local time. Any verification or write failure
causes a non-zero exit, so the host's cron/system mail or log collection should
alert operations. If the deployment target supports systemd timers with journal
collection, that is preferable to silent cron. Avoid running the export as the
same OS user that runs the app if the destination permissions can be separated.

## Verification during an audit

1. Restore or inspect the application database.
2. Choose an off-box export record. Let its `last_id` be `N`.
3. Verify `audit_log` ordered by `id ASC` through row `N`, not only the current
   latest row. The database may have advanced after the export.
4. Compare the hash at row `N` and the row count through `N` with the off-box
   JSON export.

If the database head differs from the exported head for the same `last_id`, the
audit log has been rewritten or truncated after export.

An export with `last_id = null` and null hashes means the audit chain was empty
at export time. That is acceptable during first boot but should be rare after
real traffic begins.

## Investigating a mismatch

- If the exported `last_id` is missing locally, history was truncated or the
  wrong database was inspected.
- If row `N` exists but its hash differs, one or more rows at or before `N` were
  edited and the chain was recomputed or corrupted.
- If current latest rows differ but row `N` matches, the database likely
  continued recording audit rows after the export; compare against a newer
  off-box record.
