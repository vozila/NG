# Shared Line Access Reference Pack

**Updated:** 2026-02-19 (America/New_York)

## Scope
Feature module: `features/shared_line_access.py`  
Feature gate: `VOZ_FEATURE_SHARED_LINE_ACCESS=1`

This pack documents shared-line and dedicated-line Twilio routing behavior, including **deterministic access-code resolution for `ai_mode`**.

**Canonical mode field:** `ai_mode`  
**Allowed values:** `customer` | `owner`

> NOTE: Older docs referenced `actor_mode=client|owner`. In NG, the shared-line contract uses `ai_mode=customer|owner`.
> Flow A may internally map `ai_mode` to `actor_mode` for back-compat with older policy resolvers.

---

## Endpoints
- `POST /twilio/voice`
  - Decides dedicated vs shared vs reject.
  - Shared line returns `<Gather>` to collect the access code.
- `POST /twilio/voice/access-code`
  - Validates code and returns `<Connect><Stream>` with custom parameters (tenant + mode + rid).
- `GET /_healthz`
  - Lightweight health endpoint.

---

## Twilio routing behavior

### A) Dedicated line routing
If the inbound `To` number matches `VOZ_DEDICATED_LINE_MAP_JSON[to]`, route directly to stream:

- `tenant_mode=dedicated`
- `tenant_id=<mapped>`
- `ai_mode=customer` (default)
- `rid=<CallSid>` (or fallback)

### B) Shared line routing
If `To == VOZ_SHARED_LINE_NUMBER`, respond with `<Gather>`:

- Prompt is generic: “Please enter your 8-digit access code.”
- The Gather action URL includes:
  - `attempt=<n>`
  - `rid=<CallSid>`

**Important invariant:** The Gather action query string must be XML-escaped (`&amp;`) inside TwiML.

### C) Reject routing
If `To` does not match shared line or a dedicated line key, reject politely (e.g., “Wrong number.”).

---

## Access code resolution (ai_mode selection)

Deterministic rule:
- One code resolves one `{tenant_id, ai_mode}` outcome; no runtime guessing.

### Control surface
- `VOZ_DUAL_MODE_ACCESS=0|1`
  - When OFF: legacy behavior (owner-only codes)
  - When ON: dual-mode enabled

### Preferred (dual-mode)
Use an explicit routing table:

- `VOZ_ACCESS_CODE_ROUTING_JSON='{"12345678":{"tenant_id":"tenant_demo","ai_mode":"owner"},"87654321":{"tenant_id":"tenant_demo","ai_mode":"customer"}}'`

This is unambiguous and supports multiple tenants.

### Dual-mode fallback mappings
If `VOZ_DUAL_MODE_ACCESS=1` but `VOZ_ACCESS_CODE_ROUTING_JSON` is missing/empty:

- `VOZ_CLIENT_ACCESS_CODE_MAP_JSON='{"87654321":"tenant_demo"}'`  → returns `ai_mode=customer`
- `VOZ_ACCESS_CODE_MAP_JSON='{"12345678":"tenant_demo"}'`         → returns `ai_mode=owner`

### Legacy (single-mode)
If `VOZ_DUAL_MODE_ACCESS=0`:

- `VOZ_ACCESS_CODE_MAP_JSON` is treated as **owner-only** and returns `ai_mode=owner`

---

## Stream parameter contract (Flow A)
On successful code validation, the `<Stream>` contains the following `Parameter` entries:

- `tenant_mode` (shared|dedicated)
- `rid` (CallSid; used as trace_id)
- `tenant_id`
- `ai_mode` ✅
- `from_number` / `to_number` (when available)

Flow A must treat missing/invalid `ai_mode` as **customer** (fail-closed).

---

## Environment variables
Required:
- `VOZ_FEATURE_SHARED_LINE_ACCESS=1`
- `VOZ_SHARED_LINE_NUMBER=+E164`
- `VOZ_TWILIO_STREAM_URL=wss://...`
- `VOZ_DEDICATED_LINE_MAP_JSON={}` (can be empty JSON)

Access-code / mode selection:
- `VOZ_DUAL_MODE_ACCESS=0|1`
- `VOZ_ACCESS_CODE_ROUTING_JSON` (preferred)
- `VOZ_CLIENT_ACCESS_CODE_MAP_JSON` (fallback)
- `VOZ_ACCESS_CODE_MAP_JSON` (owner map; legacy + fallback)

Optional:
- `VOZ_ACCESS_CODE_PROMPT="..."`

---

## Failure signatures (and fixes)

### 1) TwiML parse failures due to unescaped '&'
Symptom:
- Twilio errors when processing Gather action URL.

Fix:
- Ensure query separators in `action="...?...&amp;attempt=...&amp;rid=..."` are XML-escaped.

### 2) Caller always lands in owner mode
Symptom:
- `ai_mode` always resolves as owner.

Fix:
- Ensure `VOZ_DUAL_MODE_ACCESS=1` and set `VOZ_ACCESS_CODE_ROUTING_JSON` (preferred) or provide `VOZ_CLIENT_ACCESS_CODE_MAP_JSON` for customer codes.

---

## Regression coverage
`features/shared_line_access.py:selftests()` asserts:
- Shared line returns Gather with XML-safe escaped action URL
- Dual-mode resolver returns correct `(tenant_id, ai_mode)`
- Stream TwiML includes `ai_mode`
