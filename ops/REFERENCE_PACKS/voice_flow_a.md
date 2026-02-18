# Reference Pack — Flow A (Twilio ↔ OpenAI Realtime)

**Updated:** 2026-02-18 (America/New_York)

This is the canonical “golden behavior” and failure signature pack for Flow A.
Per policy: no Flow A/streaming/barge-in changes without updating this pack.

---

## 1) System model (Flow A)

Twilio → FastAPI WebSocket (`/twilio/stream`) → OpenAI Realtime (audio) → Twilio

### Key endpoints (shared line)
- `POST /twilio/voice` → TwiML Gather (ask for access code)
- `POST /twilio/voice/access-code` → validate code → TwiML Connect/Stream
- `WS /twilio/stream` → real-time audio bridge

### Required Stream customParameters
- `tenant_id=<tenant>`
- `tenant_mode=shared|dedicated`
- `rid=<CallSid>`
- (planned) `actor_mode=client|owner`

---

## 2) “Golden loop” behavior (minimal hot path)

### Twilio inbound
- Twilio sends WS events:
  - `start` (contains streamSid/callSid/customParameters)
  - `media` (base64 μ-law audio)
  - `stop`

Server behavior:
- On `start`:
  - log `TWILIO_WS_START ... tenant_id ... tenant_mode ... rid ...`
  - connect OpenAI WS (if `VOZ_FLOW_A_OPENAI_BRIDGE=1`)
  - send `session.update` with:
    - `input_audio_format=g711_ulaw`
    - `output_audio_format=g711_ulaw`
    - `turn_detection.type=server_vad`
    - `turn_detection.create_response=false` (server controls response.create)
    - transcription enabled
- On `media`:
  - enqueue payload into bounded queue (drop-oldest on overflow)

### OpenAI Realtime inbound/outbound events (minimum set)
- `session.created` / `session.updated`
- `input_audio_buffer.speech_started`  (barge-in trigger)
- `conversation.item.input_audio_transcription.completed` (text transcript)
- `response.created`
- `response.output_audio.delta` (base64 g711_ulaw bytes)
- `response.done`

Server behavior:
- On `speech_started`:
  - **barge-in**:
    - send Twilio `clear` once for that speech-start
    - cancel active OpenAI response (`response.cancel`)
    - clear queued outbound assistant audio (main lane)
- On transcript completed:
  - send `response.create`
  - IMPORTANT modalities compatibility:
    - many servers require `['audio','text']` (audio-only may be invalid)
    - best: drive from `session.output_modalities`

### Audio out (critical)
- On each `response.output_audio.delta`:
  - base64-decode to bytes (g711_ulaw)
  - chunk bytes into 160-byte frames
  - append to `buffers.main` (cap length; drop oldest)
- Sender loop:
  - every ~20ms:
    - pop from `buffers.main` (preferred)
    - send Twilio `media` event with base64 payload

---

## 3) Key invariants (do not regress)

- No DB reads/writes in WS audio loop.
- No per-frame logging (use first-delta breadcrumbs only).
- Queue bounds must exist (drop oldest) to prevent unbounded memory growth.
- `clear` should be scoped to real barge-in; avoid noise-triggered clears.

---

## 4) Minimal debug breadcrumbs (VOZLIA_DEBUG=1 only)

Expected in a healthy call:
- `TWILIO_WS_CONNECTED`
- `TWILIO_WS_START ... tenant=... tenant_mode=... rid=...`
- `OPENAI_WS_CONNECTED`
- `OPENAI_SESSION_UPDATE_SENT`
- `OPENAI_SESSION_CREATED ... output_modalities=...`
- `OPENAI_SPEECH_STARTED turn=N`
- `OPENAI_TRANSCRIPT completed len=... turn=N`
- `OPENAI_RESPONSE_CREATE_SENT ... modalities=['audio','text']`
- `OPENAI_RESPONSE_CREATED id=resp_...`
- `OPENAI_AUDIO_DELTA_FIRST response_id=... bytes=...`
- `TWILIO_MAIN_FRAME_SENT first=1 response_id=... q_main=...`

---

## 5) Failure signatures + fixes

### A) “Responses complete but no audio”
Symptom:
- `OPENAI_RESPONSE_CREATED` + `OPENAI_RESPONSE_DONE`
- no `OPENAI_AUDIO_DELTA_FIRST`
Fix:
- Verify `response.create` modalities include audio (often `['audio','text']`)
- Verify event handler listens for `response.output_audio.delta`

### B) “Invalid modalities: ['audio']”
Symptom:
- OpenAI error `invalid_value` with supported combos `['text']` and `['audio','text']`
Fix:
- Use `['audio','text']` and/or drive from `session.output_modalities`

### C) “Audio starts then gets cut off”
Symptom:
- first audio delta is seen, first Twilio frame sent, but speech is very short
Fix:
- confirm `TWILIO_CLEAR_SENT` is only on real `speech_started` (barge-in)
- consider VAD threshold/silence tuning + debounce

---

## 6) Rollback levers
- `VOZ_FLOW_A_OPENAI_BRIDGE=0` disables OpenAI bridge immediately.
- `VOZ_FEATURE_VOICE_FLOW_A=0` disables WS endpoint entirely.
