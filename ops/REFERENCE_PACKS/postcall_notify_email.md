# Reference Pack — Post-call Notify Email

**Updated:** 2026-02-21 (America/New_York)

## Scope
Feature module: `features/postcall_notify_email.py`  
Feature gate: `VOZ_FEATURE_POSTCALL_NOTIFY_EMAIL=1`  
Runtime gate: `VOZ_POSTCALL_NOTIFY_EMAIL_ENABLED=1`

Admin out-of-band notifier that turns new post-call lead/appt artifacts into owner email notifications.

## Endpoint
- `POST /admin/postcall/notify/email`
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
3. Skip any `rid` with `notify.email_sent` or `notify.email_delivery_unknown`.
4. Compose subject/body with source event and optional `postcall.summary.headline`.
5. Dry run:
   - returns plan
   - writes no notify events
6. Non-dry run:
   - sends to webhook (`VOZ_NOTIFY_EMAIL_WEBHOOK_URL`)
   - writes:
     - `notify.email_sent` (idempotency `notify_email:{rid}`)
     - `notify.email_failed` on provider failure
     - `notify.email_delivery_unknown` when provider send succeeds but DB write fails

## Required env
- `VOZ_ADMIN_API_KEY`
- `VOZ_TENANT_OWNER_NOTIFY_JSON` format includes email:
  - `{"tenant_demo":{"email":"owner@example.com"}}`
- `VOZ_NOTIFY_EMAIL_WEBHOOK_URL` (non-dry run only)

## Rollback
- Runtime off: `VOZ_POSTCALL_NOTIFY_EMAIL_ENABLED=0`
- Feature off: `VOZ_FEATURE_POSTCALL_NOTIFY_EMAIL=0`

