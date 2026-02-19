# Vozlia NG — KNOWN GOTCHAS (do not relearn)

**Updated:** 2026-02-19 (America/New_York)

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

## Shared line access codes / mode selection

### 4) The access code selects `ai_mode` — keep naming canonical
Symptom:
- Mode-specific prompts/voices never activate, or everything falls back to customer mode.

Fix:
- Ensure the Twilio Stream contract uses **`ai_mode`** with allowed values exactly:
  - `customer`
  - `owner`
- Treat missing/unknown values as `customer` (fail closed).

### 5) Dual-mode requires explicit enablement
Symptom:
- Customer codes never work; only owner codes validate.

Fix:
- Set `VOZ_DUAL_MODE_ACCESS=1`, then set either:
  - preferred: `VOZ_ACCESS_CODE_ROUTING_JSON` (code → `{tenant_id, ai_mode}`)
  - or fallback: `VOZ_CLIENT_ACCESS_CODE_MAP_JSON` + `VOZ_ACCESS_CODE_MAP_JSON`

### 6) TwiML Gather action URLs must XML-escape '&'
Symptom:
- Twilio rejects the Gather action URL or the access-code handler never receives `rid/attempt`.

Fix:
- Use `&amp;` separators inside XML attributes (e.g., `action="...?...&amp;attempt=0&amp;rid=..."`).

## Observability (general)
- Logging inside 20ms audio loops is not “free”. Keep per-frame logs OFF; use first-delta breadcrumbs only.

## Post-call extraction

### 7) `transcript_not_found` despite successful calls
Symptom:
- `POST /admin/postcall/extract` returns `{"detail":"transcript_not_found"}` even though call logs show transcript completion.

Root cause:
- `flow_a.transcript_completed` events only persisted `transcript_len` and not transcript text.

Fix:
- Ensure Flow A persists transcript text in payload:
  - `transcript` (sanitized, bounded)
  - `transcript_len`
- Then run extraction using the real call `rid` (typically `callSid`).
