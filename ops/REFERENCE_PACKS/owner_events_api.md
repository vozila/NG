# Reference Pack — Owner Events API

**Updated:** 2026-02-19 (America/New_York)

## Scope
Feature module: `features/owner_events_api.py`  
Feature gate: `VOZ_FEATURE_OWNER_EVENTS_API=1`

Read-only API for owner-facing event facts backed by `core.db.query_events(...)`.

## Auth (MVP)
- Required env: `VOZ_OWNER_API_KEY=<secret>`
- Header: `Authorization: Bearer <VOZ_OWNER_API_KEY>`
- Missing env or invalid bearer returns `401 unauthorized`.

## Endpoints
- `GET /owner/events`
  - Query:
    - `tenant_id` (required)
    - `limit` (optional, default 100, max 1000)
    - `event_type` (optional)
    - `since_ts` (optional)
    - `until_ts` (optional)
  - Response:
    - `{ "ok": true, "events": [ ...query_events rows... ] }`

- `GET /owner/events/latest`
  - Query:
    - `tenant_id` (required)
    - `event_type` (optional)
  - Response:
    - `{ "ok": true, "event": <latest row or null> }`

## Data contract
Rows are passthrough from `core.db.query_events` with keys:
- `event_id`, `tenant_id`, `rid`, `event_type`, `ts`, `payload`, `trace_id`, `idempotency_key`

Expected event types from Flow A emitter:
- `flow_a.call_started`
- `flow_a.transcript_completed`
- `flow_a.response_done`
- `flow_a.call_stopped`

## Failure model
- This module does not write to DB and does not affect Flow A hot path.
- Invalid query parameters that fail DB validation return HTTP 400.
- Feature flag OFF removes endpoint exposure.

## Rollback
- Set `VOZ_FEATURE_OWNER_EVENTS_API=0`.
