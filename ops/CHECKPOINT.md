# CHECKPOINT (rolling) — Vozlia NG

**Updated:** 2026-02-21 (America/New_York)

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
- Flow A now includes debug-gated realtime diagnostics for queue/pacing health and speech controller visibility.
- Active 3-agent bundle model is defined in `ops/AGENT_BUNDLES.md` (Bundle B001).
- Bundle B001 execution status is synchronized:
  - `TASK-0401`: DONE
  - `TASK-0402`: DONE
  - `TASK-0403`: DONE
- Required task evidence now includes checks run plus concrete render-log references in each active bundle task file.
- Bundle B003 Agent C portal delivery is recorded with mandatory verification sections; live endpoint checks remain operator-run due session/auth dependency.
- Bundle B004 is marked complete; next execution line is Bundles B005-B008 (task files and workflow script are now pre-wired).
- WebUI monorepo migration completed: portal codebase is now available at `apps/vozlia-admin` inside NG.
- True cutover executed: legacy standalone path `/Users/yasirmccarroll/Downloads/repo/vozlia-admin` removed.
- Added monorepo WebUI runner: `scripts/run_webui.sh` (`dev|build|lint|test`).
- Resolved Agent C bundle blocker conditions in `apps/vozlia-admin`:
  - `npm run lint` now passes.
  - `npm test` now exists and passes (`lint + tsc --noEmit`).

## Last known good
- Flow A OpenAI Realtime bridge: audio deltas received + Twilio μ-law frames sent + caller hears speech.
- Realtime compatibility fix is known: `response.modalities` must be `['audio','text']` (or model-supported equivalent), not `['audio']`.
- Known-good audible breadcrumbs:
  - `OPENAI_AUDIO_DELTA_FIRST ...`
  - `TWILIO_MAIN_FRAME_SENT first=1 ...`
  - `twilio_send stats: q_bytes=... frames_sent=... underruns=... late_ms_max=... prebuf=...`
  - `speech_ctrl_ACTIVE_DONE type=response.done response_id=... dt_ms=...`
- Known-good post-call extraction evidence:
  - `flow_a.transcript_completed` includes `payload.transcript`
  - `/admin/postcall/extract` returns `ok: true`
  - owner events include `postcall.summary` and `postcall.lead` for the same `rid`
- Known-good reconcile + insights evidence:
  - `/admin/postcall/reconcile` returns attempted/created/skipped/errors counts
  - `/owner/insights/summary` returns deterministic tenant-scoped counts and latest rid
  - reconcile honors bounded concurrency (`VOZ_POSTCALL_RECONCILE_CONCURRENCY`) without unbounded fan-out

## Next actions
- Install and run WebUI from monorepo path:
  - `bash scripts/run_webui.sh dev`
- Set local WebUI auth/control env vars:
  - `NEXTAUTH_URL`, `NEXTAUTH_SECRET`, `VOZLIA_CONTROL_BASE_URL`, `VOZLIA_ADMIN_KEY`
- Execute Bundle B005:
  - `bash scripts/agent_bundle_workflow.sh execute B005`
- Execute Bundle B006:
  - `bash scripts/agent_bundle_workflow.sh execute B006`
- Execute Bundle B007:
  - `bash scripts/agent_bundle_workflow.sh execute B007`
- Execute Bundle B008:
  - `bash scripts/agent_bundle_workflow.sh execute B008`
- Close Bundle B003 by running operator-side portal/API verification commands and logging outputs.
- Enforce proof-gate closeout after each bundle (`ops/BUNDLE_PROOF_GATES.md` + `scripts/bundle_gate_checklist.sh <BUNDLE_ID>`).
