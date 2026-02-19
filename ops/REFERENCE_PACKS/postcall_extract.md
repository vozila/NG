# Reference Pack — Post-call Extract

**Updated:** 2026-02-19 (America/New_York)

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
- `postcall.lead`
- `postcall.appt_request` (only when request is detected)

## Failure model
- No transcript facts found => `404 transcript_not_found`.
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
