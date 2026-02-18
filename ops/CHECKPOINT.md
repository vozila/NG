# CHECKPOINT (rolling) — Vozlia NG

**Updated:** 2026-02-18 (America/New_York)

## Last known good
- Flow A bridge is still operational with audible assistant speech.
- Actor-mode policy selection for Flow A is now implemented and guarded.

## Current Flow A Mode Behavior
- Twilio `start.customParameters.actor_mode` is read in `features/voice_flow_a.py`.
- Validation is fail-closed: unknown/missing mode defaults to `client`.
- `session.update` now uses policy-selected `voice` and `instructions`.
- Policy selector runs on `start` only (hot-path safe; no per-frame DB/compute additions).

## Policy and Env Controls
- `VOZ_FLOW_A_ACTOR_MODE_POLICY=0|1` (default OFF)
  - `0`: existing single global config behavior
  - `1`: mode-aware resolution enabled
- Tenant overrides (preferred): `VOZ_TENANT_MODE_POLICY_JSON`
- Mode globals: `VOZ_OPENAI_REALTIME_INSTRUCTIONS_CLIENT|OWNER`, `VOZ_OPENAI_REALTIME_VOICE_CLIENT|OWNER`
- Base globals fallback: `VOZ_OPENAI_REALTIME_INSTRUCTIONS`, `VOZ_OPENAI_REALTIME_VOICE`

## Expected Debug Breadcrumbs (`VOZLIA_DEBUG=1`)
- `TWILIO_WS_START ... actor_mode=...`
- `VOICE_FLOW_A_START ... actor_mode=...`
- `VOICE_MODE_SELECTED tenant_id=... actor_mode=... voice=...`

## Quality Status (TASK-0204)
- Resolver unit tests added in `tests/test_voice_flow_a.py`
- Local gates run for this task:
  - `python -m compileall .`
  - `python -c "import features.voice_flow_a"`
  - `ruff check .`
  - `pytest -q`
  - `VOZ_FEATURE_ADMIN_QUALITY=1 VOZ_FEATURE_VOICE_FLOW_A=1 python scripts/run_regression.py`

## Rollback Levers
- Emergency bridge rollback: `VOZ_FLOW_A_OPENAI_BRIDGE=0`
- Disable new actor-mode policy logic: `VOZ_FLOW_A_ACTOR_MODE_POLICY=0`
- Disable Flow A endpoint: `VOZ_FEATURE_VOICE_FLOW_A=0`
