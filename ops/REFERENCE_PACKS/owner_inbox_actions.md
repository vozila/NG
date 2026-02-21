# Reference Pack — Owner Inbox Actions

**Updated:** 2026-02-21 (America/New_York)

## Scope
Feature module: `features/owner_inbox_actions.py`  
Feature gate: `VOZ_FEATURE_OWNER_INBOX_ACTIONS=1`  
Runtime gate: `VOZ_OWNER_INBOX_ENABLED=1`

Owner action APIs for lead qualification and handled-state tracking.

## Endpoints
- `POST /owner/inbox/actions/qualify`
- `POST /owner/inbox/actions/handled`
- `GET /owner/inbox/actions/state?tenant_id=<tenant>&rid=<rid>`

Auth:
- `Authorization: Bearer <VOZ_OWNER_API_KEY>`

## Persistence events
- `owner.inbox.lead_qualified`
- `owner.inbox.handled_set`

State endpoint reads latest payload from those event types for `(tenant_id, rid)`.

## Request shapes
- qualify:
  - `tenant_id` (required)
  - `rid` (required)
  - `qualified` (bool)
  - `reason` (optional)
- handled:
  - `tenant_id` (required)
  - `rid` (required)
  - `handled` (bool)
  - `channel` (`phone|sms|email|unknown`, default `unknown`)
  - `note` (optional)

## Rollback
- Runtime off: `VOZ_OWNER_INBOX_ENABLED=0`
- Feature off: `VOZ_FEATURE_OWNER_INBOX_ACTIONS=0`

