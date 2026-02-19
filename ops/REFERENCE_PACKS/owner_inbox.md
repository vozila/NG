# Reference Pack — Owner Inbox

**Updated:** 2026-02-19 (America/New_York)

## Scope
Feature module: `features/owner_inbox.py`  
Feature gate: `VOZ_FEATURE_OWNER_INBOX=1`  
Runtime gate: `VOZ_OWNER_INBOX_ENABLED=1`

Owner-facing normalized inbox endpoints derived from durable event facts.

## Endpoints
- `GET /owner/inbox/leads`
- `GET /owner/inbox/appt_requests`

Auth:
- `Authorization: Bearer <VOZ_OWNER_API_KEY>`

Query params:
- `tenant_id` (required)
- `since_ts` (optional)
- `until_ts` (optional)
- `limit` (optional, default `50`, max `200`)

## Behavior
- Deterministic SELECT-only logic.
- Tenant isolation mandatory.
- Window bounded to max 7 days.
- Newest-first source ordering.

Leads source:
- primary `postcall.lead`
- best-effort joins by `rid`:
  - `postcall.summary.headline`
  - `flow_a.call_started.from_number`
  - `flow_a.call_started.to_number`

Appt request source:
- primary `postcall.appt_request`
- same best-effort join strategy.

Missing join fields are returned as `null` (no crash).

## Failure model
- Missing/invalid bearer => 401
- Runtime gate off => 503
- `limit > 200` => 422
- window > 7 days or invalid ordering => 400

## Rollback
- `VOZ_OWNER_INBOX_ENABLED=0` (runtime)
- `VOZ_FEATURE_OWNER_INBOX=0` (feature)
