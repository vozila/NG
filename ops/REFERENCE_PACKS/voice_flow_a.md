# Reference Pack — Flow A Actor Mode Policy (Twilio ↔ OpenAI Realtime)

**Updated:** 2026-02-18 (America/New_York)

This pack defines Flow A actor-mode behavior and rollback levers.

## 1) Actor Mode Meaning
- `actor_mode=client`: customer-facing assistant behavior.
- `actor_mode=owner`: owner-facing assistant behavior (analytics/admin persona, no customer-service tone).
- Unknown or missing actor mode must default to `client` (fail closed).

## 2) How Actor Mode Is Set
- Shared-line access code resolves to tenant context in access-gate flow.
- Access gate passes values through Twilio `<Stream><Parameter .../>` into `start.customParameters`.
- Flow A reads from:
  - `start.customParameters.tenant_id`
  - `start.customParameters.actor_mode`

## 3) Policy Resolution (Env-first)
Gate:
- `VOZ_FLOW_A_ACTOR_MODE_POLICY=0|1` (default `0`).

When policy gate is `0`:
- Existing global behavior only:
  - `VOZ_OPENAI_REALTIME_VOICE` (fallback `marin`)
  - `VOZ_OPENAI_REALTIME_INSTRUCTIONS`

When policy gate is `1`:
1. Validate `actor_mode` to `client|owner` (else `client`).
2. Resolve tenant/mode override from `VOZ_TENANT_MODE_POLICY_JSON`:
   - shape: `{ "tenant_id": { "client": {"instructions": "...", "voice": "..."}, "owner": {...} } }`
3. If missing, resolve mode globals:
   - `VOZ_OPENAI_REALTIME_INSTRUCTIONS_CLIENT|OWNER`
   - `VOZ_OPENAI_REALTIME_VOICE_CLIENT|OWNER`
4. If still missing, fallback to existing globals:
   - `VOZ_OPENAI_REALTIME_INSTRUCTIONS`
   - `VOZ_OPENAI_REALTIME_VOICE`
5. If still missing, keep safe defaults (voice `marin`, instructions omitted).

## 4) Expected Debug Breadcrumbs (`VOZLIA_DEBUG=1`)
- `TWILIO_WS_START ... actor_mode=...`
- `VOICE_FLOW_A_START ... actor_mode=...`
- `VOICE_MODE_SELECTED tenant_id=... actor_mode=... voice=...`

No per-frame logging changes. Existing first-delta breadcrumbs remain unchanged.

## 5) Session Update Contract
`session.update` must continue to send selected `voice` and `instructions` plus existing Flow A transport config:
- `modalities=["audio","text"]`
- `input_audio_format=g711_ulaw`
- `output_audio_format=g711_ulaw`
- `turn_detection.type=server_vad`
- `turn_detection.create_response=false`

## 6) Rollback Levers
- Emergency rollback: `VOZ_FLOW_A_OPENAI_BRIDGE=0`
- Disable actor-mode policy logic only: `VOZ_FLOW_A_ACTOR_MODE_POLICY=0`
- Full Flow A endpoint off: `VOZ_FEATURE_VOICE_FLOW_A=0`
