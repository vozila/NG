# Reference Pack — Owner Analytics Query

**Updated:** 2026-02-19 (America/New_York)

## Scope
Feature module: `features/owner_analytics_query.py`  
Feature gate: `VOZ_FEATURE_OWNER_ANALYTICS_QUERY=1`  
Runtime gate: `VOZ_OWNER_ANALYTICS_QUERY_ENABLED=1`

Owner-authenticated deterministic analytics endpoint with strict QuerySpec and safe SQL execution.

## Endpoint
- `POST /owner/analytics/query`
- Auth:
  - `Authorization: Bearer <VOZ_OWNER_API_KEY>`

## Request contract
Strict JSON (Pydantic):
- `tenant_id` (required)
- `since_ts` / `until_ts` (optional; default last 24h)
- `query`:
  - `metrics` allowed:
    - `count_calls`
    - `count_leads`
    - `count_appt_requests`
    - `count_transcripts`
  - `dimensions` allowed:
    - `day`
    - `event_type`
    - `ai_mode`
  - `filters`:
    - `event_types` allowlist
    - `ai_modes` allowlist (`customer|owner`)
  - `limit <= 200`

## Deterministic safety rules
- Tenant isolation always enforced (`WHERE tenant_id = ?`).
- SELECT-only execution path.
- Bounded window:
  - max 7 days (`window exceeds max 7 days` => 400)
- QuerySpec validation:
  - invalid metric/dimension => 422
  - limit > 200 => 422

## Response shape
- `ok`, `tenant_id`, `window`, `query`, `rows`, `totals`

`rows` are grouped by requested dimensions (or single aggregate row when no dimensions).  
`totals` sums each requested metric across rows.

Limit semantics:
- `query.limit` is applied when dimensions are present (grouped result rows).
- When no dimensions are requested, response is a single aggregate row and limit has no effect on row count.

## Rollback
- Runtime off: `VOZ_OWNER_ANALYTICS_QUERY_ENABLED=0`
- Feature off: `VOZ_FEATURE_OWNER_ANALYTICS_QUERY=0`
