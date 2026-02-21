# Reference Pack — Scheduler Tick

**Updated:** 2026-02-21 (America/New_York)

## Scope
Feature module: `features/scheduler_tick.py`  
Feature gate: `VOZ_FEATURE_SCHEDULER_TICK=1`  
Runtime gate: `VOZ_SCHEDULER_ENABLED=1`

Admin scheduler tick runner for due active goals.

## Endpoint
- `POST /admin/scheduler/tick`

Auth:
- `Authorization: Bearer <VOZ_ADMIN_API_KEY>`

Request body:
- `tenant_id` (required)
- `limit` (optional, default `20`, max `200`)
- `dry_run` (optional, default `true`)
- `now_ts` (optional deterministic clock override)

## Behavior
- Reconstructs goal state from wizard goal lifecycle events.
- Selects due goals where:
  - status is `active`
  - `next_run_ts <= now_ts`
- Non-dry run emits `scheduler.goal_executed` with idempotency:
  - `scheduler_tick:{goal_id}:{slot_ts}`

## Rollback
- Runtime off: `VOZ_SCHEDULER_ENABLED=0`
- Feature off: `VOZ_FEATURE_SCHEDULER_TICK=0`

