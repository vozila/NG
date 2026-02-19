# Vozlia NG — DECISIONS

## 2026-02-15 — Day 0
- One-file feature modules in `features/` with `FEATURE` contract.
- Feature flags default OFF via `VOZ_FEATURE_<NAME>`.
- Regression runner report written to `ops/QUALITY_REPORTS/latest_regression.json`.
## 2026-02-15 — Day 1
- Voice “thinking audio” mitigation: Flow A will use explicit waiting hooks and later a separate aux audio lane to avoid fighting barge-in + buffers. Initial waiting hooks are included in TASK-0100.
- Evidence policy: `ops/QUALITY_REPORTS/latest_regression.json` is committed for Day 0 baseline only. Subsequent gate runs should snapshot to timestamped files (log + regression snapshot) and avoid committing the rolling report unless explicitly requested.
- Automation: prefer `scripts/run_gates_record.sh` for uploadable logs; `scripts/clean_generated.sh` to keep feature branches clean.

## 2026-02-17 — Flow A “thinking chime” as a first-class state (aux audio lane)
- We will NOT “inject” a chime into the same outbound buffer as assistant speech. Instead:
  - Maintain 2 independent outbound lanes:
    - main lane: assistant speech audio (OpenAI Realtime deltas)
    - aux lane: waiting/thinking comfort tone
  - Sender rule: always prefer main; only send aux when main is empty and thinking audio is active.
  - On barge-in / user speech while waiting: stop thinking audio immediately and clear only aux
    (do not clear/cancel main unless an actual assistant response is being canceled).
- Waiting/thinking audio activation is deterministic:
  - start WAIT when a tool/skill begins
  - after `VOICE_WAIT_SOUND_TRIGGER_MS` (default 800ms) enter THINKING and enable aux lane
  - stop immediately when the tool/skill completes
- Default safety posture:
  - `VOICE_WAIT_CHIME_ENABLED` defaults OFF; enable only after parity tests.
  - All waiting/chime logs remain gated behind `VOZLIA_DEBUG=1`.
- Implementation pattern:
  - `WaitingAudioController` is pure/deterministic and unit-tested.
  - Mu-law “beep frames” are precomputed once at import time to avoid hot-path CPU.

## 2026-02-18 — Actor mode is first-class (client vs owner)

Decision:
- Introduce `actor_mode` as a first-class call context dimension alongside `tenant_id` and `tenant_mode`.
- Shared-line access codes resolve to `{tenant_id, actor_mode}` and propagate via Twilio Stream `start.customParameters`.

Implications:
- Mode-specific instructions/persona are selected by `(tenant_id, actor_mode)` with no heavy work in the voice hot path.
- Feature/skill execution must be mode-aware and **fail closed** (owner-only operations are denied in client mode).
- Configuration is env-first for MVP (JSON maps), with DB-backed policy later.

## 2026-02-18 — Realtime response.create must request supported modalities

Decision:
- Do not assume `['audio']` is a valid response modality.
- Drive `response.create.response.modalities` from `session.output_modalities` (fallback to `['audio','text']`).
- Treat `invalid_value` on `response.modalities` as a compatibility signal and force the supported combo.

## 2026-02-18 — Access code selects ai_mode and propagates into Flow A

Decision:
- Access code selects ai_mode (customer vs owner) and mode is propagated into Flow A.

Implications:
- Shared-line resolver returns `{tenant_id, ai_mode}` and passes `ai_mode` via `start.customParameters.ai_mode`.
- Mode-specific protocols/instructions must be selected by `(tenant_id, ai_mode)` with fail-closed defaults.

## 2026-02-19 — Owner events are exposed via a feature-flagged read API

Decision:
- Add a read-only owner API surface backed by `core.db.query_events(...)`:
  - `GET /owner/events`
  - `GET /owner/events/latest`
- Gate endpoint exposure with `VOZ_FEATURE_OWNER_EVENTS_API=1`.
- Require bearer token auth via `VOZ_OWNER_API_KEY`; deny with 401 if key missing or invalid.

Implications:
- Owner mode and analytics can consume durable `flow_a.*` facts without touching Flow A WS hot path.
- Emergency rollback is immediate by setting `VOZ_FEATURE_OWNER_EVENTS_API=0`.
