# Vozlia WebUI Patch — DBQuery Proxy Fix + Render Logs Panel + Status Badge (2026-02-05)

## What this patch does
1) Fixes DBQuery API proxy routes:
- Uses `VOZLIA_CONTROL_BASE_URL` (consistent with WebSearch routes)
- Uses `X-Vozlia-Admin-Key: <VOZLIA_ADMIN_KEY>` header (consistent with Control/Backend)
This restores:
- DBQuery skill list / delete
- DBQuery schedules
- DBQuery run

2) Restores/Upgrades **Render Logs** panel:
- Adds proxy routes:
  - `/api/admin/render/services`
  - `/api/admin/render/logs`
- Updates RenderLogsPanel to:
  - select a service
  - query the correct required params (service_id/start_ms/end_ms)
  - refresh + optional auto-refresh

3) Adds a lightweight **System Status** badge panel:
- Calls `/api/admin/diag/regression` (proxy to control plane) every 30s.
- Shows OK / DEGRADED and per-check indicators.

## Apply
Copy the files from this zip into your webui repo root, preserving paths.

## Required env
These already exist for WebSearch, but DBQuery now relies on them too:
- `VOZLIA_CONTROL_BASE_URL`
- `VOZLIA_ADMIN_KEY`

## Smoke tests
1) Admin page:
- System Status panel shows OK.
- Render Logs shows services and log lines (no more HTTP 400).
2) DBQuery panel:
- Existing DB skills appear.
- Delete works.
- Schedules list/edit works.
