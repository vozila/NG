# CHECKPOINT (rolling) — Vozlia NG

**Updated:** 2026-02-19 (America/New_York)

## Current state
- Access code routing deterministically selects `ai_mode` (`customer|owner`) and propagates it to Flow A.
- TASK-0203 and TASK-0204 are completed and treated as settled contract behavior.
- Flow A reference pack remains source-of-truth for audible bridge behavior and failure signatures.
- Owner read-surface is available behind feature flag via `GET /owner/events` and `GET /owner/events/latest`.
- Post-call extraction endpoint is available behind feature/runtime gates (`VOZ_FEATURE_POSTCALL_EXTRACT`, `VOZ_POSTCALL_EXTRACT_ENABLED`), with admin bearer auth.
- Post-call extraction proposer is model-first (Responses API JSON schema) with deterministic heuristic fallback and strict validation before writes.
- Flow A now persists transcript text on `flow_a.transcript_completed` payloads (`transcript` + `transcript_len`), enabling post-call extraction reads.
- Post-call reconcile runner is available behind feature/runtime gates (`VOZ_FEATURE_POSTCALL_RECONCILE`, `VOZ_POSTCALL_RECONCILE_ENABLED`).
- Owner insights summary endpoint is available behind `VOZ_FEATURE_OWNER_INSIGHTS`.
- Reconcile runner now scans recent stopped calls first and uses bounded concurrency for extraction triggers.
- Flow A lifecycle events now persist caller metadata (`from_number`, `to_number`) on `flow_a.call_started` and `flow_a.call_stopped`.
- Owner inbox endpoints are available behind gates (`VOZ_FEATURE_OWNER_INBOX`, `VOZ_OWNER_INBOX_ENABLED`).
- Postcall SMS notifier is available behind gates (`VOZ_FEATURE_POSTCALL_NOTIFY_SMS`, `VOZ_POSTCALL_NOTIFY_SMS_ENABLED`).

## Last known good
- Flow A OpenAI Realtime bridge: audio deltas received + Twilio μ-law frames sent + caller hears speech.
- Realtime compatibility fix is known: `response.modalities` must be `['audio','text']` (or model-supported equivalent), not `['audio']`.
- Known-good audible breadcrumbs:
  - `OPENAI_AUDIO_DELTA_FIRST ...`
  - `TWILIO_MAIN_FRAME_SENT first=1 ...`
- Known-good post-call extraction evidence:
  - `flow_a.transcript_completed` includes `payload.transcript`
  - `/admin/postcall/extract` returns `ok: true`
  - owner events include `postcall.summary` and `postcall.lead` for the same `rid`
- Known-good reconcile + insights evidence:
  - `/admin/postcall/reconcile` returns attempted/created/skipped/errors counts
  - `/owner/insights/summary` returns deterministic tenant-scoped counts and latest rid
  - reconcile honors bounded concurrency (`VOZ_POSTCALL_RECONCILE_CONCURRENCY`) without unbounded fan-out

## Next actions
- Add/verify feature gating via `VOZ_FEATURE_<NAME>_AI_MODES`.
- Build owner analytics views on top of durable `flow_a.*` and `postcall.*` facts.
- Roll out caller metadata contract consumers across owner automations (inbox/notify workflows).
- Validate owner inbox UI integration against normalized `/owner/inbox/*` endpoints.
- Stage SMS notifier rollout (`dry_run` first, then enable live sends per tenant mapping).
