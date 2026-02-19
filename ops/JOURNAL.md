# JOURNAL (append-only) — Vozlia NG

**Timezone:** America/New_York

## 2026-02-19 — Flow A realtime observability diagnostics hardening

What changed:
- Updated `features/voice_flow_a.py` with debug-gated realtime diagnostics focused on audio quality triage:
  - sender stats (`q_bytes`, `frames_sent`, `underruns`, `late_ms_max`, `prebuf`)
  - speech-control heartbeat (`qsize`, `active_response_id`)
  - response lifecycle timing (`speech_ctrl_ACTIVE_DONE ... dt_ms=...`)
  - explicit VAD/barge-in breadcrumbs.
- Added env knobs:
  - `VOICE_TWILIO_STATS_EVERY_MS` (default `1000`)
  - `VOICE_TWILIO_PREBUFFER_FRAMES` (default `6`)
  - `VOICE_SPEECH_CTRL_HEARTBEAT_MS` (default `2000`)
- Added queue-bytes helper test coverage in `tests/test_voice_flow_a.py`.
- Synced ops references/gotchas for interpretation and safe usage.

Proof (<=5):
- `ruff check features/voice_flow_a.py tests/test_voice_flow_a.py` ✅
- `.venv/bin/python -m pytest -q tests/test_voice_flow_a.py` ✅ (`17 passed`)
- `.venv/bin/python -m pytest -q` ✅ (`73 passed`)

## 2026-02-19 — TASK-0224/0225/0226/0227 delivery + ops sync

What changed:
- TASK-0224:
  - `flow_a.call_started` and `flow_a.call_stopped` payload contracts now persist `from_number` and `to_number`.
- TASK-0225:
  - added owner inbox feature module:
    - `GET /owner/inbox/leads`
    - `GET /owner/inbox/appt_requests`
  - deterministic tenant-scoped normalization with best-effort summary/caller joins.
- TASK-0226:
  - added postcall SMS notifier module:
    - `POST /admin/postcall/notify/sms`
  - dry-run planning mode and non-dry idempotent send path (`notify.sms_sent`/`notify.sms_failed`).
- TASK-0227:
  - synced memory spine + drift control docs for this batch (`TASKBOARD`, `CHECKPOINT`, `DECISIONS`, `CODE_DRIFT_CONTROL`).

Proof (<=5):
- `ruff check features/voice_flow_a.py features/owner_inbox.py features/postcall_notify_sms.py tests/test_voice_flow_a.py tests/test_owner_inbox.py tests/test_postcall_notify_sms.py` ✅
- `.venv/bin/python -m pytest -q tests/test_voice_flow_a.py tests/test_owner_inbox.py tests/test_postcall_notify_sms.py` ✅

## 2026-02-19 — Reconcile runner efficiency pass (recent-first + bounded concurrency)

What changed:
- Updated `features/postcall_reconcile.py`:
  - reconcile now scans `flow_a.call_stopped` rows in recent-first order (`ORDER BY ts DESC`)
  - extraction triggers now execute with bounded concurrency using a semaphore
  - new env knob: `VOZ_POSTCALL_RECONCILE_CONCURRENCY` (bounded `1..10`, default `4`)
- Added tests for:
  - recent-first behavior with `limit=1`
  - bounded concurrency cap enforcement
- Updated reference docs to clarify:
  - reconcile recent-first/cap behavior
  - owner analytics query `limit` semantics with and without dimensions

Proof (<=5):
- `ruff check features/postcall_reconcile.py tests/test_postcall_reconcile.py` ✅
- `.venv/bin/python -m pytest -q tests/test_postcall_reconcile.py` ✅
- `.venv/bin/python -m pytest -q` ✅

## 2026-02-19 — TASK-0216 reconcile runner + TASK-0215 owner insights summary

What changed:
- Added `features/postcall_reconcile.py`:
  - `POST /admin/postcall/reconcile` (admin bearer)
  - scans tenant `flow_a.call_stopped` events, skips existing `postcall.summary`, triggers internal `/admin/postcall/extract`
  - uses `ai_mode` from call-stopped payload
  - uses idempotency key `reconcile-{rid}-v1`
  - bounded request (`limit<=200`) and includes optional `dry_run`
  - debug signatures:
    - `POSTCALL_RECONCILE_START ...`
    - `POSTCALL_RECONCILE_DONE attempted=... created=... skipped=... errors=...`
- Added `features/owner_insights.py`:
  - `GET /owner/insights/summary` (owner bearer)
  - deterministic tenant-scoped counts over `flow_a.*` and `postcall.*`
  - default window last 24h, bounded max window 7 days
  - debug signature:
    - `OWNER_INSIGHTS_SUMMARY tenant_id=... since_ts=... until_ts=...`
- Added task docs and reference packs:
  - `.agents/tasks/TASK-0216.md`, `.agents/tasks/TASK-0215.md`
  - `ops/REFERENCE_PACKS/postcall_reconcile.md`, `ops/REFERENCE_PACKS/owner_insights.md`

Proof (<=5):
- `ruff check features/postcall_reconcile.py features/owner_insights.py tests/test_postcall_reconcile.py tests/test_owner_insights.py` ✅
- `.venv/bin/python -m pytest -q tests/test_postcall_reconcile.py tests/test_owner_insights.py` ✅

## 2026-02-19 — Flow A transcript payload persistence fix for post-call extraction

What changed:
- Patched `features/voice_flow_a.py` so `flow_a.transcript_completed` now stores transcript text in event payload:
  - `transcript` (sanitized whitespace, bounded length)
  - `transcript_len`
- This resolves extractor read failures where only transcript length was persisted.
- Verified production behavior:
  - owner events show transcript text on transcript-completed events
  - `/admin/postcall/extract` returns `ok: true`
  - output events `postcall.summary` and `postcall.lead` are written for the same `rid`

Proof (<=5):
- `ruff check features/voice_flow_a.py tests/test_voice_flow_a.py` ✅
- `.venv/bin/python -m pytest -q tests/test_voice_flow_a.py tests/test_postcall_extract.py` ✅ (`19 passed`)
- Owner events payload includes `"transcript":"..."` on `flow_a.transcript_completed` ✅
- Extract endpoint response includes `ok: true` with emitted event ids ✅

## 2026-02-19 — TASK-0213 post-call extraction model-first + fallback hardening

What changed:
- `features/postcall_extract.py` now uses model-first extraction for proposer output:
  - OpenAI Responses API (`/v1/responses`) with strict JSON schema format.
- Added deterministic fallback to local heuristic proposer when model path is disabled or errors.
- Preserved fail-closed contract:
  - proposer output must pass strict Pydantic validation
  - invalid schema writes `postcall.extract_failed` and returns `422`
- Added debug breadcrumbs (debug-gated):
  - `POSTCALL_EXTRACT_MODEL_USED ...`
  - `POSTCALL_EXTRACT_FALLBACK_USED ...`
- Updated docs for auth and approach consistency:
  - admin bearer key for endpoint (`VOZ_ADMIN_API_KEY`)
  - model knobs and fallback behavior documented.

Proof (<=5):
- `ruff check features/postcall_extract.py tests/test_postcall_extract.py` ✅
- `.venv/bin/python -m pytest -q tests/test_postcall_extract.py` ✅ (`5 passed`)
- `.venv/bin/python -m pytest -q` ✅ (`34 passed`)

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
