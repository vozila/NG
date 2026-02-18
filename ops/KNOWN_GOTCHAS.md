# Vozlia NG — KNOWN GOTCHAS (do not relearn)

**Updated:** 2026-02-18 (America/New_York)

## Flow A (Twilio WS ↔ OpenAI Realtime)

### 1) Realtime `response.modalities=['audio']` may be invalid
Symptom:
- You see `OPENAI_RESPONSE_CREATE_SENT` then an OpenAI error:
  - `code=invalid_value`
  - message includes: supported combinations are `['text']` and `['audio','text']`

Fix:
- Use `['audio','text']` for `response.create.response.modalities`, preferably driven from `session.output_modalities`.

Evidence signature:
- `OPENAI_ERROR ... param='response.modalities' message="Invalid modalities: ['audio'] ..."`

### 2) No audible speech even though responses complete
Symptom:
- `OPENAI_RESPONSE_CREATED`/`OPENAI_RESPONSE_DONE` occur
- No `response.output_audio.delta` events
- No Twilio outbound frame logs

Checklist:
- Confirm `response.create` modalities include audio (`['audio','text']`)
- Confirm you are listening for `response.output_audio.delta` (and optional alias `response.audio.delta`)
- Confirm you are chunking g711_ulaw bytes into **160-byte** frames and pacing ~20ms per frame
- Confirm Twilio sender loop is actually sending frames (not always empty)

### 3) Over-aggressive Twilio `clear` can truncate speech
Symptom:
- You get `OPENAI_AUDIO_DELTA_FIRST` and `TWILIO_MAIN_FRAME_SENT`, but callers hear only a tiny fragment.

Fix:
- Send `clear` only on a true `speech_started` (barge-in) event.
- Consider debouncing noise-triggered speech_started (threshold tuning) before clearing.

## Observability (general)
- Logging inside 20ms audio loops is not “free”. Keep per-frame logs OFF; use first-delta breadcrumbs only.
