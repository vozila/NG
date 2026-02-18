# CHECKPOINT (rolling) — Vozlia NG

**Updated:** 2026-02-18 (America/New_York)

## Last known good (production-like)
- Render primary URL: https://vozlia-ng.onrender.com
- Shared line: +15186668613
- Confirmed on: 2026-02-18 (callSid CAea5b686da6471efc79785a0071246885)
- Proof: caller heard the assistant; logs showed first audio delta + first Twilio main frame.

## What’s working

### Shared-line routing + access
- `/twilio/voice` returns Gather for access code
- `/twilio/voice/access-code` validates and returns Connect/Stream
- `start.customParameters` includes `tenant_id`, `tenant_mode=shared`, `rid=<CallSid>`

### Flow A voice hot path (Twilio WS + OpenAI Realtime)
- Twilio WS connects: `TWILIO_WS_CONNECTED`
- OpenAI WS connects and session update accepted:
  - `OPENAI_WS_CONNECTED`
  - `OPENAI_SESSION_UPDATE_SENT`
  - `OPENAI_SESSION_CREATED ...`
  - `OPENAI_SESSION_UPDATED ...`
- Server VAD + transcript loop working:
  - `OPENAI_SPEECH_STARTED`
  - `OPENAI_TRANSCRIPT completed ...`
  - `OPENAI_RESPONSE_CREATE_SENT ...`
  - `OPENAI_RESPONSE_CREATED ...`
  - `OPENAI_RESPONSE_DONE ...`
- **Audio out working (audible):**
  - `OPENAI_AUDIO_DELTA_FIRST ...`
  - `TWILIO_MAIN_FRAME_SENT first=1 ...`

## What’s broken / risky
- Barge-in clearing may be overly aggressive (multiple `TWILIO_CLEAR_SENT` events can truncate model audio).
- No dual-mode (client vs owner) routing yet; currently access code maps to tenant only.

## Required env vars (Render)
Feature flags / routing:
- `VOZ_FEATURE_SHARED_LINE_ACCESS=1`
- `VOZ_FEATURE_VOICE_FLOW_A=1`
- `VOZ_SHARED_LINE_NUMBER=+15186668613`
- `VOZ_ACCESS_CODE_MAP_JSON={"12345678":"tenant_demo"}`  (current; owner-only semantics today)
- `VOZ_DEDICATED_LINE_MAP_JSON={}`
- `VOZ_TWILIO_STREAM_URL=wss://vozlia-ng.onrender.com/twilio/stream`

Realtime bridge:
- `VOZ_FLOW_A_OPENAI_BRIDGE=1`
- `OPENAI_API_KEY=<valid>`
- Optional:
  - `VOZ_OPENAI_REALTIME_MODEL=gpt-realtime`
  - `VOZ_OPENAI_REALTIME_VOICE=<voice>`
  - `VOZ_OPENAI_REALTIME_INSTRUCTIONS=<string>`

Debug:
- `VOZLIA_DEBUG=1` (development only)

## Next actions (ordered)
1. Implement dual-mode access codes: access code → `{tenant_id, actor_mode}` and propagate to Stream customParameters.
2. Add mode policy enforcement (MVP env-only): mode-specific instructions and mode-aware feature/skill gating (fail closed).
3. Refine barge-in/clear semantics and add deterministic tests for mid-response interruption.

## Rollback levers (fast)
- `VOZ_FLOW_A_OPENAI_BRIDGE=0` disables OpenAI bridge immediately (Twilio stream still works).
- `VOZ_FEATURE_VOICE_FLOW_A=0` disables WS endpoint entirely.
- `VOZ_FEATURE_SHARED_LINE_ACCESS=0` disables access gate routing.
