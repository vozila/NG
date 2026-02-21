# Reference Pack — Post-call Extract

**Updated:** 2026-02-21 (America/New_York)

## Scope
Feature module: `features/postcall_extract.py`  
Feature gate: `VOZ_FEATURE_POSTCALL_EXTRACT=1`  
Runtime gate: `VOZ_POSTCALL_EXTRACT_ENABLED=1`

Out-of-band extraction endpoint that reads call transcript facts and writes structured events.

## Endpoint
- `POST /admin/postcall/extract`
- Body:
  - `tenant_id` (required)
  - `rid` (required)
  - `ai_mode` (`customer|owner`)
  - `idempotency_key` (required)

## Auth
- Bearer token using admin key pattern.
- Required env key:
  - `VOZ_ADMIN_API_KEY`
- Missing/invalid token => `401 unauthorized`.

## Execution model
Deterministic shape:
1. Read transcript facts for `(tenant_id, rid)` from event store.
   - Required source payload fields from Flow A events:
     - `flow_a.transcript_completed.payload.transcript` (or `text`)
     - `flow_a.transcript_completed.payload.transcript_len` retained for metadata
2. Proposer returns JSON object:
   - Primary: model extraction call (`/v1/responses`) with strict JSON schema output.
   - Fallback: deterministic heuristic proposer if model is disabled, missing key, timeout, or errors.
3. Pydantic strictly validates JSON schema.
4. Python writes structured events.

Model knobs:
- `VOZ_POSTCALL_EXTRACT_MODEL_ENABLED=0|1` (default `1`)
- `VOZ_POSTCALL_EXTRACT_MODEL` (default `gpt-4o-mini`)
- `OPENAI_API_KEY` required for model path

Debug signatures (`VOZLIA_DEBUG=1`):
- `POSTCALL_EXTRACT_MODEL_USED model=... ai_mode=...`
- `POSTCALL_EXTRACT_FALLBACK_USED reason=model_disabled`
- `POSTCALL_EXTRACT_FALLBACK_USED reason=model_error err=...`

Output event types:
- `postcall.summary`
- `postcall.lead` (customer mode only)
- `postcall.appt_request` (customer mode only, and only when request is detected)

## Extraction v2 fields (TASK-0243)
Additional schema fields now emitted when present:
- `postcall.summary` payload:
  - `urgency`: `low|medium|high`
  - `action_items`: list of concise follow-up items (max 5)
- `postcall.lead` payload:
  - `callback_requested`: bool
  - `talk_to_owner`: bool
  - `preferred_contact`: `phone|sms|email|unknown`

Heuristic proposer defaults:
- `urgency=high` when transcript requests owner/manager escalation.
- `callback_requested=true` on callback phrases (`call me`, `callback`, `call back`).

Mode-aware output policy:
- `ai_mode=customer`:
  - emits `postcall.summary`
  - may emit `postcall.lead`
  - may emit `postcall.appt_request`
- `ai_mode=owner`:
  - emits `postcall.summary` only
  - does not emit `postcall.lead` or `postcall.appt_request`

## Failure model
- No transcript facts found => `404 transcript_not_found`.
  - Common cause: transcript events exist but payload only contains `transcript_len` without `transcript` text.
- Schema-invalid proposer output:
  - write `postcall.extract_failed` with reason
  - return `422 schema_invalid`
- Runtime gate disabled => `503 postcall extraction disabled`.

## Idempotency model
Stable idempotency keys per output event:
- `postcall_extract:{rid}:{idempotency_key}:summary`
- `postcall_extract:{rid}:{idempotency_key}:lead`
- `postcall_extract:{rid}:{idempotency_key}:appt_request`
- failure path: `...:failed`

Same `(tenant_id, rid, idempotency_key)` will not duplicate written events.

## Tenant isolation
- Reads use `query_events_for_rid(tenant_id, rid, event_type=...)`.
- Extraction payload for one tenant cannot include facts from another tenant, even when `rid` collides.

## Rollback
- Set `VOZ_POSTCALL_EXTRACT_ENABLED=0` to keep feature loaded but inactive.
- Set `VOZ_FEATURE_POSTCALL_EXTRACT=0` to remove route exposure.

## Runbook — Verify In Production
1. Confirm routes are mounted:
   - `curl -sS https://vozlia-ng.onrender.com/openapi.json | jq -r '.paths | keys[]' | grep -E '^/admin/postcall/extract$|^/owner/events$'`
   - Expect both `/admin/postcall/extract` and `/owner/events`.

2. Validate owner read auth + recent call facts:
   - `curl -sS "https://vozlia-ng.onrender.com/owner/events?tenant_id=tenant_demo&limit=20" -H "Authorization: Bearer $VOZ_OWNER_API_KEY"`
   - Expect `flow_a.*` events for a recent call rid.

3. Confirm transcript payload is present:
   - `flow_a.transcript_completed.payload.transcript` must exist (not only `transcript_len`).

4. Run extraction for that rid:
   - `RID='<real_call_rid>'`
   - `curl -sS -X POST "https://vozlia-ng.onrender.com/admin/postcall/extract" -H "Authorization: Bearer $VOZ_ADMIN_API_KEY" -H "Content-Type: application/json" -d "{\"tenant_id\":\"tenant_demo\",\"rid\":\"$RID\",\"ai_mode\":\"owner\",\"idempotency_key\":\"demo-$RID-v1\"}"`
   - Customer mode expect: `{"ok":true,...,"events":{"summary":"...","lead":"..."}}` (and optional `appt_request`).
   - Owner mode expect: `{"ok":true,...,"events":{"summary":"..."}}`.

5. Verify writes in owner events feed:
   - `curl -sS "https://vozlia-ng.onrender.com/owner/events?tenant_id=tenant_demo&limit=50" -H "Authorization: Bearer $VOZ_OWNER_API_KEY"`
   - Customer mode: expect new `postcall.summary` and `postcall.lead` (optional `postcall.appt_request`).
   - Owner mode: expect only `postcall.summary`.

6. Verify idempotency:
   - Re-run step 4 with same `idempotency_key`.
   - Expect no duplicate `postcall.summary`/`postcall.lead` writes.
