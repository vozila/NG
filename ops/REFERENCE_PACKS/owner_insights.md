# Reference Pack — Owner Insights Summary

**Updated:** 2026-02-19 (America/New_York)

## Scope
Feature module: `features/owner_insights.py`  
Feature gate: `VOZ_FEATURE_OWNER_INSIGHTS=1`

Owner-authenticated deterministic analytics endpoint over tenant event-store facts.

## Endpoint
- `GET /owner/insights/summary`
- Query:
  - `tenant_id` (required)
  - `since_ts` (optional)
  - `until_ts` (optional)
- Auth:
  - `Authorization: Bearer <VOZ_OWNER_API_KEY>`

## Behavior
- Tenant isolation for all reads (`WHERE tenant_id = ?`).
- No OpenAI calls.
- Window handling:
  - default to last 24h when missing
  - bounded to max 7 days
  - invalid window (`since_ts > until_ts`) returns 400

## Returned counts
- `call_started` (`flow_a.call_started`)
- `call_stopped` (`flow_a.call_stopped`)
- `transcript_completed` (`flow_a.transcript_completed`)
- `postcall_summary` (`postcall.summary`)
- `leads_total` (`postcall.lead`)
- `leads_qualified` (`postcall.lead` with `qualified=true`)
- `appt_requests` (`postcall.appt_request`)

Also returns latest `(rid, ts)` in the selected window.

## Logging (debug only)
- `OWNER_INSIGHTS_SUMMARY tenant_id=... since_ts=... until_ts=...`

## Rollback
- `VOZ_FEATURE_OWNER_INSIGHTS=0`
