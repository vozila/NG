# Vozlia NG — KNOWN GOTCHAS (do not relearn)

**Updated:** 2026-02-18 (America/New_York)

## Flow A (Twilio WS ↔ OpenAI Realtime)

### 1) OpenAI response.modalities must be ['audio','text'] (NOT ['audio'])
Symptom:
- `OPENAI_ERROR` with `param='response.modalities'` and `code='invalid_value'`.

Fix:
- Send `response.create.response.modalities=['audio','text']` (or a model-supported combo from `session.output_modalities`).

### 2) Twilio μ-law frame size 160 bytes; chunking required
Symptom:
- Responses complete but no audible speech, or stutter/garble from malformed frame boundaries.

Fix:
- Decode each `response.output_audio.delta`, then split bytes into 160-byte chunks and pace to Twilio at ~20ms intervals.

### 3) TWILIO_CLEAR_SENT only at speech_started / barge-in boundaries
Symptom:
- Assistant audio is repeatedly truncated or disappears after small noise events.

Fix:
- Send `clear` only when a true user barge-in starts (`speech_started` boundary), not on generic state changes.
- Add debounce/guards so noise does not trigger unnecessary clears.

## Observability (general)
- Logging inside 20ms audio loops is not “free”. Keep per-frame logs OFF; use first-delta breadcrumbs only.
