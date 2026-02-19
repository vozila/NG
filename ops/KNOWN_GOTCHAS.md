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

### 9) Realtime diagnostics can still hurt audio if overused
Symptom:
- Voice quality degrades when debug logging is left on for long calls.

Fix:
- Keep `VOZLIA_DEBUG=0` by default in production.
- When troubleshooting, use bounded windows and rely on summary signatures:
  - `twilio_send stats ...`
  - `speech_ctrl_HEARTBEAT ...`
  - `speech_ctrl_ACTIVE_DONE ...`

### 10) How to read `twilio_send stats` quickly
Symptom:
- Intermittent clipping, delayed starts, or robotic pacing.

Interpretation:
- `underruns` rising: sender had no frame available; expect audible gaps.
- `late_ms_max` high spikes (e.g. 100ms+): event-loop scheduling or contention issue.
- `prebuf=True` for too long: startup buffering delay.
- `q_bytes` large and not draining: output backlog / pacing mismatch.

Related knobs:
- `VOICE_TWILIO_STATS_EVERY_MS`
- `VOICE_TWILIO_PREBUFFER_FRAMES`
- `VOICE_SPEECH_CTRL_HEARTBEAT_MS`

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

### 8) Reconcile internal callback fails due to disallowed `VOZ_SELF_BASE_URL`
Symptom:
- `POST /admin/postcall/reconcile` returns higher `errors` than expected.
- Security checks indicate invalid `VOZ_SELF_BASE_URL` host.

Root cause:
- Reconcile now validates callback host before sending admin bearer.
- Host must be local/known-safe (`127.0.0.1`, `localhost`, `::1`, Render hostnames, or explicit allowlist).

Fix:
- Set `VOZ_SELF_BASE_URL` to a safe internal URL (default loopback is preferred).
- If a non-default trusted host is required, add it via:
  - `VOZ_SELF_BASE_URL_ALLOWED_HOSTS=host1,host2`
