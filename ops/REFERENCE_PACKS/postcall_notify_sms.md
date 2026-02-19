# Reference Pack — Post-call Notify SMS

**Updated:** 2026-02-19 (America/New_York)

## Scope
Feature module: `features/postcall_notify_sms.py`  
Feature gate: `VOZ_FEATURE_POSTCALL_NOTIFY_SMS=1`  
Runtime gate: `VOZ_POSTCALL_NOTIFY_SMS_ENABLED=1`

Admin out-of-band notifier that turns new post-call lead/appt artifacts into owner SMS notifications.

## Endpoint
- `POST /admin/postcall/notify/sms`
- Auth:
  - `Authorization: Bearer <VOZ_ADMIN_API_KEY>`
- Request body (strict):
  - `tenant_id` (required)
  - `since_ts` (required)
  - `limit` (default `50`, max `200`)
  - `dry_run` (default `true`)

## Behavior
1. Scan tenant-scoped events since `since_ts` for:
   - `postcall.lead`
   - `postcall.appt_request`
2. Process newest-first, dedupe by `rid`.
3. Skip any `rid` that already has `notify.sms_sent`.
4. Compose SMS text from:
   - source event type (lead/appt)
   - `postcall.summary.headline` (best-effort)
   - `flow_a.call_started.from_number` (best-effort)
5. Dry run:
   - returns planned sends
   - writes no events
6. Non-dry run:
   - sends via Twilio REST
   - writes:
     - `notify.sms_sent` (idempotency key `notify_sms:{rid}`)
     - `notify.sms_failed` on send failure
     - `notify.sms_delivery_unknown` if provider send succeeds but DB write for `notify.sms_sent` fails

## Required env
- Auth:
  - `VOZ_ADMIN_API_KEY`
- Destination map:
  - `VOZ_TENANT_OWNER_NOTIFY_JSON`
    - format: `{"tenant_demo":{"sms":"+1..."}}`
- Twilio:
  - `VOZ_TWILIO_ACCOUNT_SID`
  - `VOZ_TWILIO_AUTH_TOKEN`
  - `VOZ_TWILIO_SMS_FROM`

## Failure model
- Missing/invalid admin bearer => `401`
- Runtime gate off => `503`
- Missing tenant destination => `400`
- Missing Twilio config on non-dry run => `503`
- `limit > 200` => `422`
- If persistence fails after successful provider send, endpoint records `notify.sms_delivery_unknown` and future runs skip that rid to avoid duplicate SMS sends.

## Rollback
- Runtime off: `VOZ_POSTCALL_NOTIFY_SMS_ENABLED=0`
- Feature off: `VOZ_FEATURE_POSTCALL_NOTIFY_SMS=0`
