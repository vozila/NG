# Vozlia NG — TASKBOARD
**Date:** 2026-02-20 (America/New_York)

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
- [x] TASK-0203 — Dual-mode access gating (`ai_mode=customer|owner`) on the shared number
      - Generic prompt: “enter your 8-digit access code”
      - Access code resolves `{tenant_id, ai_mode}`
      - Pass `ai_mode` through Twilio Stream customParameters
- [x] TASK-0204.1 — Back-compat and routing config for access-code mode selection
      - Preferred `VOZ_ACCESS_CODE_ROUTING_JSON` for code -> `{tenant_id, ai_mode}`
      - Keep `VOZ_ACCESS_CODE_MAP_JSON` as legacy owner map
      - Optional `VOZ_CLIENT_ACCESS_CODE_MAP_JSON` for customer codes
- [x] TASK-0204 — Flow A `ai_mode` policy selection (MVP env-only)
      - Mode-specific instructions/voice selected by `(tenant_id, ai_mode)` via env-config JSON
      - Flow A logs include `ai_mode=...` for routing clarity
- [x] TASK-0212 — Owner Events API + memory spine sync
      - New feature module: `owner_events_api` (read-only, feature-flagged)
      - Endpoints: `GET /owner/events`, `GET /owner/events/latest`
      - Auth: `Authorization: Bearer <VOZ_OWNER_API_KEY>` (denies when key missing/invalid)
      - Backed by `core.db.query_events(...)`
- [x] TASK-0213 — Post-call extraction (summary + lead + appointment request)
      - Endpoint: `POST /admin/postcall/extract`
      - Auth: `Authorization: Bearer <VOZ_ADMIN_API_KEY>`
      - Gating: `VOZ_FEATURE_POSTCALL_EXTRACT=1` + `VOZ_POSTCALL_EXTRACT_ENABLED=1`
      - Proposer: model-first (`/v1/responses` JSON schema) with deterministic heuristic fallback
      - Writes: `postcall.summary`, `postcall.lead`, optional `postcall.appt_request`
      - Fail-closed: schema invalid writes `postcall.extract_failed` + returns `422`
- [x] TASK-0216 — Post-call reconcile runner (admin, out-of-band)
      - Endpoint: `POST /admin/postcall/reconcile`
      - Auth: `Authorization: Bearer <VOZ_ADMIN_API_KEY>`
      - Gating: `VOZ_FEATURE_POSTCALL_RECONCILE=1` + `VOZ_POSTCALL_RECONCILE_ENABLED=1`
      - Scans tenant `flow_a.call_stopped`, skips existing `postcall.summary`, triggers internal `/admin/postcall/extract`
      - Uses `ai_mode` from `flow_a.call_stopped.payload` and idempotency key `reconcile-{rid}-v1`
      - Added `dry_run` support and bounded `limit<=200`
- [x] TASK-0215 — Owner insights summary (deterministic analytics, owner-only)
      - Endpoint: `GET /owner/insights/summary`
      - Auth: `Authorization: Bearer <VOZ_OWNER_API_KEY>`
      - Gate: `VOZ_FEATURE_OWNER_INSIGHTS=1`
      - Deterministic tenant-scoped counts over `flow_a.*` and `postcall.*` events
      - Defaults to last 24h window and bounds to max 7 days
- [x] TASK-0224 — Flow A lifecycle event contract includes caller metadata
      - `flow_a.call_started.payload` includes `from_number`, `to_number`
      - `flow_a.call_stopped.payload` includes `from_number`, `to_number`
      - Additive payload-only change; no schema changes
- [x] TASK-0225 — Owner Inbox API (deterministic, owner-auth)
      - Endpoints: `GET /owner/inbox/leads`, `GET /owner/inbox/appt_requests`
      - Auth: `Authorization: Bearer <VOZ_OWNER_API_KEY>`
      - Gates: `VOZ_FEATURE_OWNER_INBOX=1` + `VOZ_OWNER_INBOX_ENABLED=1`
      - Tenant-scoped SELECT-only normalization with best-effort summary/caller joins
- [x] TASK-0226 — Postcall SMS notifier (admin, out-of-band)
      - Endpoint: `POST /admin/postcall/notify/sms`
      - Auth: `Authorization: Bearer <VOZ_ADMIN_API_KEY>`
      - Gates: `VOZ_FEATURE_POSTCALL_NOTIFY_SMS=1` + `VOZ_POSTCALL_NOTIFY_SMS_ENABLED=1`
      - Supports dry-run planning and idempotent non-dry send/write path (`notify.sms_sent`)
- [x] Flow A realtime observability diagnostics hardening
      - Added debug-gated sender/speech-controller diagnostics for audio quality triage
      - New env knobs:
        - `VOICE_TWILIO_STATS_EVERY_MS`
        - `VOICE_TWILIO_PREBUFFER_FRAMES`
        - `VOICE_SPEECH_CTRL_HEARTBEAT_MS`
      - Signatures include:
        - `twilio_send stats ...`
        - `speech_ctrl_HEARTBEAT ...`
        - `speech_ctrl_ACTIVE_DONE ...`

## NOW (next high-leverage work)
- [ ] TASK-0401 — Flow A chunk-mode pacing parity (hot path safety)
      - Keep `VOICE_TWILIO_CHUNK_MODE` default ON without startup clipping regressions
      - Enforce startup prebuffer/start-buffer and refill-hysteresis in chunk mode
      - Preserve stable pacing equivalent to 20ms/frame
- [ ] TASK-0402 — Render log tooling hardening + operator workflow docs
      - Capture rotation/retry reliability
      - Barge-in latency analysis and per-call extraction workflows
      - Reference-pack sync for current chunk/pacing behavior
- [ ] TASK-0403 — 3-agent bundle orchestration (ops memory spine sync)
      - Active bundle policy with non-overlapping file ownership
      - Required checks + log-review protocol per agent
      - Assignment and status discipline across `.agents/tasks/*`
- [ ] TASK-0207 — Mode-aware capability gating (MVP env-only; **fail closed**)
      - Per-feature allowlist: `VOZ_FEATURE_<NAME>_AI_MODES="customer,owner"` (or single)
      - Owner-only features/skills must reject customer mode deterministically
      - Default behavior for unknown modes: treat as `customer`
- [ ] TASK-0205 — Owner-mode analytics foundations (owner-only)
      - QuerySpec schema (strict JSON) + deterministic executor (SQL/DB reads only)
      - Must not run in Flow A hot path; consume facts via owner events read API
- [ ] TASK-0206 — Customer-mode capabilities (MVP)
      - Customer greeting + customer protocols
      - Lead capture / appointment request capture (domain stubs acceptable)
      - Notifications (SMS/email) behind feature flags
- [ ] Flow A: refine barge-in / clear semantics (anti-regression)
      - Ensure `TWILIO_CLEAR_SENT` only on actual `speech_started`
      - Add deterministic tests for: (a) user interrupts mid-response, (b) silence/noise edge cases

## NEXT (blocked / staged)
- [ ] Unified engine router interface (shared across voice/whatsapp/portal)
- [ ] Portal chat goal wizard (VOZ-PRD-GOALS-001) — out-of-band planning + deterministic playbooks
- [ ] Capacity Agent load profiles against staging (never prod by default)

## Guardrails (do not break)
- No cross-feature imports.
- Every feature behind `VOZ_FEATURE_<NAME>` default OFF.
- Debug logs only when `VOZLIA_DEBUG=1` (no per-frame spam).
- Before merge: `python -m compileall .` + `ruff check .` + `pytest` + regression run.

## Rollback levers (fast)
- `VOZ_FLOW_A_OPENAI_BRIDGE=0` disables OpenAI bridge immediately (Twilio stream still works).
- `VOZ_FEATURE_VOICE_FLOW_A=0` disables WS endpoint entirely.
- `VOZ_FEATURE_SHARED_LINE_ACCESS=0` disables shared-line routing/access gate.
- `VOZ_DUAL_MODE_ACCESS=0` reverts to legacy (owner-only) access-code behavior.
