# Shared Line Access Reference Pack

## Scope
Feature module: `features/shared_line_access.py`  
Feature gate: `VOZ_FEATURE_SHARED_LINE_ACCESS=1`

This pack documents shared-line and dedicated-line Twilio routing behavior, including dual-mode access-code resolution for `actor_mode`.

## Endpoints
- `POST /twilio/voice`
- `POST /twilio/voice/access-code`
- `GET /_healthz`

## Environment Variables
- `VOZ_FEATURE_SHARED_LINE_ACCESS`
  - Required feature gate. If disabled, handlers reject via runtime guard.
- `VOZ_SHARED_LINE_NUMBER`
  - Shared line E.164 number.
- `VOZ_TWILIO_STREAM_URL`
  - Required stream URL. Must start with `wss://`.
- `VOZ_DEDICATED_LINE_MAP_JSON`
  - JSON object `{to_number: tenant_id}` for dedicated routing.
- `VOZ_ACCESS_CODE_PROMPT` (optional)
  - Shared-line gather prompt override.
  - Default: `Please enter your 8 digit access code.`
- `VOZ_ACCESS_CODE_TABLE_JSON` (preferred)
  - JSON object: `{code8: {"tenant_id": "...", "actor_mode": "owner|client"}}`.
  - Validation:
    - key is exactly 8 digits
    - `tenant_id` is non-empty string
    - `actor_mode` is `owner` or `client`
- `VOZ_ACCESS_CODE_MAP_JSON` (back-compat owner map)
  - JSON object: `{code8: tenant_id}` interpreted as owner mode.
- `VOZ_CLIENT_ACCESS_CODE_MAP_JSON` (new client map)
  - JSON object: `{code8: tenant_id}` interpreted as client mode.
- `VOZLIA_DEBUG`
  - When `1`, debug breadcrumbs are emitted.

## Mode Resolution Rules
Shared-line access code resolution returns `{tenant_id, actor_mode}` using this precedence:
1. If `VOZ_ACCESS_CODE_TABLE_JSON` is present and valid, use it exclusively.
2. Else if code is found in `VOZ_CLIENT_ACCESS_CODE_MAP_JSON`, resolve `actor_mode=client`.
3. Else if code is found in `VOZ_ACCESS_CODE_MAP_JSON`, resolve `actor_mode=owner`.
4. Else invalid code.

Back-compat guarantee:
- If only `VOZ_ACCESS_CODE_MAP_JSON` is set, valid codes resolve as `owner`.

Dedicated-line routing:
- No access code step.
- Connects immediately with `tenant_mode=dedicated` and `actor_mode=client` as safe default.

## TwiML / Stream Custom Parameters
`<Connect><Stream>` includes:
- `tenant_mode`
- `rid`
- `tenant_id` (when available)
- `actor_mode` (`owner` or `client`)
- `from_number` (when available)
- `to_number` (when available)

Shared-line gather action URL must XML-escape query separators (`&amp;`).

## Debug Signatures (VOZLIA_DEBUG=1)
- Request breadcrumbs:
  - `request received: /twilio/voice ...`
  - `request received: /twilio/voice/access-code ...`
- Routing breadcrumbs:
  - Dedicated includes tenant and actor mode
  - Shared include actor mode when known
- Access result breadcrumbs:
  - `access granted: tenant_id=<id> actor_mode=<owner|client>`
  - `access denied: retry attempt=<n>`
  - `access denied: max retries`

## Failure Signatures
- `VOZ_SHARED_LINE_NUMBER missing`
- `VOZ_TWILIO_STREAM_URL missing`
- `VOZ_TWILIO_STREAM_URL must start with wss://`
- `<ENV_NAME> invalid JSON: ...`
- `<ENV_NAME> must be a JSON object`
- `<ENV_NAME> must map non-empty strings`
- `VOZ_ACCESS_CODE_TABLE_JSON must map 8-digit codes`
- `VOZ_ACCESS_CODE_TABLE_JSON value must include tenant_id and actor_mode`
- `VOZ_ACCESS_CODE_TABLE_JSON actor_mode must be 'client' or 'owner'`
- `Feature disabled: VOZ_FEATURE_SHARED_LINE_ACCESS=0`

## Rollback Levers
Soft rollback (mode semantics):
- Unset `VOZ_ACCESS_CODE_TABLE_JSON`
- Unset `VOZ_CLIENT_ACCESS_CODE_MAP_JSON`
- Keep only `VOZ_ACCESS_CODE_MAP_JSON` for owner-only behavior.

Hard rollback:
- Set `VOZ_FEATURE_SHARED_LINE_ACCESS=0`
