# Reference Pack — Post-call Reconcile

**Updated:** 2026-02-19 (America/New_York)

## Scope
Feature module: `features/postcall_reconcile.py`  
Feature gate: `VOZ_FEATURE_POSTCALL_RECONCILE=1`  
Runtime gate: `VOZ_POSTCALL_RECONCILE_ENABLED=1`

Admin out-of-band runner that backfills missing post-call outputs by reusing existing extraction endpoint logic.

## Endpoint
- `POST /admin/postcall/reconcile`
- Auth:
  - `Authorization: Bearer <VOZ_ADMIN_API_KEY>`
- Request body (strict):
  - `tenant_id` (required)
  - `since_ts` (default `0`)
  - `limit` (default `50`, max `200`)
  - `dry_run` (default `false`)

## Execution model
1. Query `flow_a.call_stopped` events for `(tenant_id, since_ts, limit)`.
   - Ordering is recent-first (`ORDER BY ts DESC`) so bounded runs prioritize newest calls.
2. For each `rid`, skip if `postcall.summary` already exists.
3. Use `ai_mode` from call-stopped payload.
4. Trigger internal HTTP call to:
   - `POST /admin/postcall/extract`
   - idempotency key: `reconcile-{rid}-v1`
5. Return batch summary counts.

## Internal call config
- `VOZ_SELF_BASE_URL`:
  - default: `http://127.0.0.1:${PORT}`
- `VOZ_POSTCALL_RECONCILE_TIMEOUT_MS`:
  - default: `3000`
- `VOZ_POSTCALL_RECONCILE_CONCURRENCY`:
  - default: `4`
  - bounded `1..10`

Internal extract call is run off-loop using `asyncio.to_thread(...)` to avoid blocking async handler execution.
Batched trigger calls run with bounded concurrency (semaphore) for predictable load.

## Response shape
- `ok`, `tenant_id`, `attempted`, `created`, `skipped`, `errors`, `dry_run`

## Logging (debug only)
- `POSTCALL_RECONCILE_START tenant_id=... since_ts=... limit=...`
- `POSTCALL_RECONCILE_DONE attempted=N created=M skipped=K errors=E`

## Rollback
- Runtime off: `VOZ_POSTCALL_RECONCILE_ENABLED=0`
- Feature off: `VOZ_FEATURE_POSTCALL_RECONCILE=0`
