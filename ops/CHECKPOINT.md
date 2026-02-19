# CHECKPOINT (rolling) — Vozlia NG

**Updated:** 2026-02-19 (America/New_York)

## Current state
- Access code routing deterministically selects `ai_mode` (`customer|owner`) and propagates it to Flow A.
- TASK-0203 and TASK-0204 are completed and treated as settled contract behavior.
- Flow A reference pack remains source-of-truth for audible bridge behavior and failure signatures.
- Owner read-surface is available behind feature flag via `GET /owner/events` and `GET /owner/events/latest`.
- Post-call extraction endpoint is available behind feature/runtime gates (`VOZ_FEATURE_POSTCALL_EXTRACT`, `VOZ_POSTCALL_EXTRACT_ENABLED`), with admin bearer auth.
- Post-call extraction proposer is model-first (Responses API JSON schema) with deterministic heuristic fallback and strict validation before writes.

## Last known good
- Flow A OpenAI Realtime bridge: audio deltas received + Twilio μ-law frames sent + caller hears speech.
- Realtime compatibility fix is known: `response.modalities` must be `['audio','text']` (or model-supported equivalent), not `['audio']`.
- Known-good audible breadcrumbs:
  - `OPENAI_AUDIO_DELTA_FIRST ...`
  - `TWILIO_MAIN_FRAME_SENT first=1 ...`

## Next actions
- Add/verify feature gating via `VOZ_FEATURE_<NAME>_AI_MODES`.
- Build owner analytics views on top of durable `flow_a.*` events.
