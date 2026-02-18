# CHECKPOINT (rolling) — Vozlia NG

**Updated:** 2026-02-18 (America/New_York)

## Current state
- Planning and continuity docs now treat access code routing as the selector for `ai_mode`.
- Canonical mode labels are `ai_mode=customer` and `ai_mode=owner`.
- Flow A reference pack is updated as the source of truth for audio bridge behavior and failure signatures.

## Last known good
- Flow A OpenAI Realtime bridge: audio deltas received + Twilio μ-law frames sent + caller hears speech.
- Realtime compatibility fix is known: `response.modalities` must be `['audio','text']` (or model-supported equivalent), not `['audio']`.

## Next actions
- Implement TASK-0203: access code resolves `{tenant_id, ai_mode}` and passes `start.customParameters.ai_mode`.
- Implement TASK-0204: enforce mode-specific instructions/protocols by `(tenant_id, ai_mode)` with fail-closed defaults.
- Add/verify feature gating via `VOZ_FEATURE_<NAME>_AI_MODES`.
