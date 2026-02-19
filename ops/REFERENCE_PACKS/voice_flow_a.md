# Reference Pack — Voice Flow A (Twilio ↔ OpenAI Realtime)

**Updated:** 2026-02-19 (America/New_York)

## 1) Golden behavior loop shape
1. Twilio `start` arrives with `customParameters` including `tenant_id`, `tenant_mode`, and `ai_mode`.
2. Flow A configures OpenAI Realtime session (`g711_ulaw` in/out, VAD settings, voice/instructions).
3. Twilio inbound audio (`media`) is forwarded to OpenAI input buffer.
4. OpenAI emits transcript/completion events, then `response.output_audio.delta`.
5. Server decodes each delta payload, chunks to 160-byte μ-law frames, and enqueues paced outbound frames.
6. Twilio sender loop emits frames to caller; caller hears assistant speech.
7. On barge-in (`speech_started`), clear/cancel semantics apply immediately.

## 2) Cancel/clear semantics
- `TWILIO_CLEAR_SENT` only at speech_started / barge-in boundaries.
- On true barge-in while assistant audio is queued/playing:
  - send Twilio `clear`
  - cancel active OpenAI response when applicable
  - stop any waiting/chime aux audio
- Do not send `clear` on generic state transitions (response created, transcript events, etc.).

## 3) Audio delta -> μ-law chunking
- Input event: `response.output_audio.delta` base64 payload from OpenAI.
- Decode payload to raw g711 μ-law bytes.
- Twilio media frame size target: 160 bytes (20ms at 8kHz μ-law).
- Chunk decoded bytes into exact 160-byte frames.
- Queue and send frames at pacing interval (~20ms/frame) to avoid burst/jitter artifacts.

## 4) Failure signatures and fixes
### A) Modalities validation failure
- Signature:
  - `OPENAI_ERROR ... param='response.modalities' ... invalid_value`
  - Error text indicates valid sets include `['text']` and `['audio','text']`.
- Fix:
  - OpenAI response.modalities must be ['audio','text'] (NOT ['audio']).
  - Prefer model/session-supported modalities from `session.output_modalities`.

### B) No audible speech despite response lifecycle events
- Signature:
  - `response.created/response.done` appear, but no `OPENAI_AUDIO_DELTA_FIRST`, or no Twilio frame sends.
- Fix checklist:
  - Confirm audio-inclusive modalities (`['audio','text']`).
  - Confirm delta listener handles `response.output_audio.delta`.
  - Confirm Twilio μ-law frame size 160 bytes; chunking required.
  - Confirm sender loop pacing and queue drain are active.

### C) Truncated speech from over-clearing
- Signature:
  - `OPENAI_AUDIO_DELTA_FIRST` appears, but user hears clipped/partial output.
- Fix:
  - Enforce clear only on actual barge-in boundaries.
  - Add debounce/guards around noisy `speech_started` edges.

## 5) Dual AI mode propagation
- Access code routing decides AI mode per tenant:
  - `ai_mode=customer` for customer-facing protocols
  - `ai_mode=owner` for owner-facing analytics/protocols
- Flow A reads mode from `start.customParameters.ai_mode`.
- Mode affects protocol selection:
  - voice/instructions persona selection by `(tenant_id, ai_mode)`
  - owner-only operations denied when mode is `customer` (fail closed on unknown/missing mode)

## 6) Env routing and policy knobs (MVP-safe)
- Preferred mapping: `VOZ_ACCESS_CODE_ROUTING_JSON`
  - code -> `{tenant_id, ai_mode}`
- Back-compat: `VOZ_ACCESS_CODE_MAP_JSON` remains legacy owner map.
- Optional customer map: `VOZ_CLIENT_ACCESS_CODE_MAP_JSON`.
- Feature mode convention: `VOZ_FEATURE_<NAME>_AI_MODES=customer,owner`.

## 7) Durable call events (hot-path safe gate)
- Kill-switch: `VOZ_FLOW_A_EVENT_EMIT=0|1` (default `0`).
- Storage: writes via `core.db.emit_event` (uses `VOZ_DB_PATH`).
- Non-blocking discipline:
  - Emission runs off-loop via `asyncio.to_thread(...)`.
  - DB failures are fail-open for audio/WS loop.
- Allowed emit points only:
  - Twilio `start` -> `flow_a.call_started`
  - transcript completion -> `flow_a.transcript_completed`
  - model response done -> `flow_a.response_done`
  - Twilio `stop`/disconnect/cleanup -> `flow_a.call_stopped`
- Required payload baseline on every event:
  - `tenant_id`, `rid`, `ai_mode`, `tenant_mode`
- Event payload contract (lifecycle):
  - `flow_a.call_started.payload` must include:
    - `from_number`, `to_number`
  - `flow_a.call_stopped.payload` must include:
    - `from_number`, `to_number`
- Transcript-completed payload contract:
  - include `transcript_len` and `transcript` text (sanitized/bounded) so downstream post-call extraction can operate.
