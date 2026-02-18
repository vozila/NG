# Vozlia NG — TASKBOARD
**Date:** 2026-02-18 (America/New_York)

## DONE
- [x] Day 0 Milestone: NG skeleton + loader + registry + admin_quality + sample + scripts + gates green
- [x] TASK-0100 — Voice Flow A WS skeleton + waiting-audio hooks (Slice A+B)
- [x] TASK-0101 — Shared line access gate (out-of-band HTTP FSM)
- [x] TASK-0102 — WhatsApp inbound adapter stub
- [x] Flow A waiting/thinking audio lane foundation: `WaitingAudioController` + aux lane + tests
      (chime default OFF via `VOICE_WAIT_CHIME_ENABLED=0`)
- [x] TASK-0201.5 — Flow A audible assistant speech (Realtime audio out)
      - OpenAI emits `response.output_audio.delta`
      - Server chunks to 160-byte μ-law frames and enqueues “main lane”
      - Twilio sender loop paces frames back to caller (audible confirmed)
      - Evidence signatures:
        - `OPENAI_AUDIO_DELTA_FIRST ...`
        - `TWILIO_MAIN_FRAME_SENT first=1 ...`
- [x] Flow A OpenAI Realtime bridge: audio deltas received + Twilio μ-law frames sent + caller hears speech
- [x] Flow A Realtime session update accepted + transcript-driven response loop working
      - `session.created/session.updated` accepted
      - `speech_started` → `transcript.completed` → `response.create` → `response.created/done`

## NOW (next high-leverage work)
- [ ] TASK-0203 — Dual-mode access gating (`ai_mode=customer|owner`) on the shared number
      - Generic prompt: “enter your 8-digit access code”
      - Access code resolves `{tenant_id, ai_mode}`
      - Pass `ai_mode` through Twilio Stream customParameters
- [ ] TASK-0204 — Mode policy enforcement (MVP env-only)
      - Mode-specific instructions by `(tenant_id, ai_mode)`
      - Mode-aware feature/skill allowlists via `VOZ_FEATURE_<NAME>_AI_MODES` (fail closed)
- [ ] TASK-0204.1 — Back-compat and routing config for access-code mode selection
      - Preferred `VOZ_ACCESS_CODE_ROUTING_JSON` for code -> `{tenant_id, ai_mode}`
      - Keep `VOZ_ACCESS_CODE_MAP_JSON` as legacy owner map
      - Optional `VOZ_CLIENT_ACCESS_CODE_MAP_JSON` for customer codes
- [ ] Flow A: refine barge-in / clear semantics (anti-regression)
      - Ensure `TWILIO_CLEAR_SENT` only on actual `speech_started`
      - Add debounce/guards so we don’t flush model audio unnecessarily
      - Add deterministic tests for: (a) user interrupts mid-response, (b) silence/noise edge cases
- [ ] Unified engine router interface (shared across voice/whatsapp/webui)

## NEXT (blocked / staged)
- [ ] Owner analytics (owner-mode only) — QuerySpec → deterministic SQL (blocked by DB readiness + schema)
- [ ] Client-mode domain features (orders / appointment requests) with notifications (blocked by domain persistence)

## Guardrails (do not break)
- No cross-feature imports.
- Every feature behind `VOZ_FEATURE_<NAME>` default OFF.
- Debug logs only when `VOZLIA_DEBUG=1` (no per-frame spam).
- Before merge: `python -m compileall .` + `ruff check .` + `pytest` + regression run.

## Rollback levers (fast)
- `VOZ_FLOW_A_OPENAI_BRIDGE=0` disables OpenAI bridge immediately (Twilio stream still works).
- `VOZ_FEATURE_VOICE_FLOW_A=0` disables WS endpoint entirely.
- `VOZ_FEATURE_SHARED_LINE_ACCESS=0` disables shared-line routing/access gate.
