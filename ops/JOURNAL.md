# JOURNAL (append-only) — Vozlia NG

**Timezone:** America/New_York

## 2026-02-19 — TASK-0212 owner events API (read surface) + memory spine sync

What changed:
- Added `features/owner_events_api.py` behind `VOZ_FEATURE_OWNER_EVENTS_API`.
- Added read-only endpoints:
  - `GET /owner/events`
  - `GET /owner/events/latest`
- Added simple bearer auth:
  - env secret: `VOZ_OWNER_API_KEY`
  - header: `Authorization: Bearer <VOZ_OWNER_API_KEY>`
  - deny (401) if secret missing or token invalid.
- Backed API reads by `core.db.query_events(...)`.
- Synced continuity docs to reflect:
  - TASK-0203 and TASK-0204 are DONE
  - access code deterministically selects `ai_mode`
  - Flow A audible known-good signatures are stable.

Proof (<=5):
- `python3 -m compileall .` ✅
- `python3 -c "import features.owner_events_api"` ✅
- `ruff check .` ✅
- `.venv/bin/python -m pytest -q tests/test_owner_events_api.py` ✅

## 2026-02-18 — Flow A audio out milestone (TASK-0201.5)

What changed:
- Updated Flow A to request valid modalities (`['audio','text']`) and handle `response.output_audio.delta`.
- Added first-delta and first-frame breadcrumbs (debug-only) to prove audio is flowing to Twilio.
- Confirmed caller hears speech.

Proof logs (<=5):
- `OPENAI_RESPONSE_CREATE_SENT rid=1 modalities=['audio','text']`
- `OPENAI_RESPONSE_CREATED id=resp_...`
- `OPENAI_AUDIO_DELTA_FIRST response_id=resp_... bytes=800`
- `TWILIO_MAIN_FRAME_SENT first=1 response_id=resp_... bytes=160 q_main=4`
- Caller heard speech.

Rollback:
- `VOZ_FLOW_A_OPENAI_BRIDGE=0`

## 2026-02-18 — TASK-0204 (actor-mode policy) writeback

What changed:
- Added mode policy selection for Flow A based on `actor_mode` (now sourced from `ai_mode`).
- Added env-only tenant policy JSON to select different voice/instructions for owner vs client.

Tests:
- `./.venv/bin/python -m compileall .` ✅
- `./.venv/bin/python -c "import features.voice_flow_a"` ✅
- `./.venv/bin/ruff check .` ✅
- `./.venv/bin/python -m pytest -q` ✅ (`23 passed`)
- `VOZ_FEATURE_ADMIN_QUALITY=1 VOZ_FEATURE_VOICE_FLOW_A=1 ./.venv/bin/python scripts/run_regression.py` ✅ (`status: ok`)

Rollback:
- Emergency: `VOZ_FLOW_A_OPENAI_BRIDGE=0`
- Disable actor-mode policy only: `VOZ_FLOW_A_ACTOR_MODE_POLICY=0`

## 2026-02-18 — OPS-0300 docs writeback (dual ai_mode + Flow A milestone)
What changed:
- Updated planning + continuity docs to formalize `ai_mode=customer|owner` selected by access code, plus MVP env mapping and feature-mode convention.
- Captured Flow A audio bridge milestone as last-known-good and refreshed Flow A reference pack with loop semantics and fixes.

Proof logs (<=5):
- `OPENAI_RESPONSE_CREATE_SENT ... modalities=['audio','text']`
- `OPENAI_RESPONSE_CREATED ...`
- `OPENAI_AUDIO_DELTA_FIRST ...`
- `TWILIO_MAIN_FRAME_SENT first=1 ... bytes=160`
- Caller heard speech.

## 2026-02-18 — TASK-0203 + TASK-0204 completion sync (ai_mode) + memory spine writeback
What changed:
- Marked TASK-0203 as DONE and standardized terminology on `ai_mode=customer|owner` (no more `actor_mode` in shared-line contract).
- Updated `ops/REFERENCE_PACKS/shared_line_access.md` to reflect the real env surface: `VOZ_DUAL_MODE_ACCESS`, `VOZ_ACCESS_CODE_ROUTING_JSON`, `VOZ_CLIENT_ACCESS_CODE_MAP_JSON`, `VOZ_ACCESS_CODE_MAP_JSON`.
- Updated `ops/TASKBOARD.md` + `ops/CHECKPOINT.md` to reflect tasks complete and moved the next gating work into a new TASK-0207.
- Updated `ops/KNOWN_GOTCHAS.md` with the ai_mode naming + TwiML escaping pitfalls.

Proof (<=5):
- `python -m compileall .` ✅
- `uvx ruff check .` ✅
- `pytest -q` ✅ (`23 passed`)
