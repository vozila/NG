# Reference Pack — Control-Plane Auth Policy

**Updated:** 2026-02-19 (America/New_York)

## Policy
- `/admin/*` routes use admin bearer auth:
  - env: `VOZ_ADMIN_API_KEY`
  - header: `Authorization: Bearer <VOZ_ADMIN_API_KEY>`
- `/owner/*` routes use owner bearer auth:
  - env: `VOZ_OWNER_API_KEY`
  - header: `Authorization: Bearer <VOZ_OWNER_API_KEY>`

## Fail-closed behavior
- If required key env var is missing, requests are unauthorized.
- Invalid or missing bearer token returns `401 unauthorized`.

## Current module mapping
- Admin:
  - `features/admin_quality.py`
  - `features/postcall_extract.py`
- Owner:
  - `features/owner_events_api.py`
