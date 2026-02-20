# Reference Pack — Business Profile API

## Feature flag + auth
- `VOZ_FEATURE_BUSINESS_PROFILE=1`
- `VOZ_OWNER_BUSINESS_PROFILE_ENABLED=1` (optional runtime gate, default enabled)
- `VOZ_OWNER_API_KEY=<secret>`
- Header: `Authorization: Bearer <VOZ_OWNER_API_KEY>`

## Endpoints
- `GET /owner/business/profile?tenant_id=<tenant>`
- `PUT /owner/business/profile`
- `DELETE /owner/business/profile?tenant_id=<tenant>`

## Canonical curl commands
```bash
curl -sS -X PUT 'http://localhost:8000/owner/business/profile' \
  -H "Authorization: Bearer ${VOZ_OWNER_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "tenant_id":"tenant_demo",
    "business_name":"Glow Studio",
    "phone":"+15180001111",
    "email":"hello@example.com",
    "timezone":"America/New_York",
    "address":"123 Main St",
    "services":["facial","laser"],
    "notes":"Owner prefers short scripts"
  }'

curl -sS "http://localhost:8000/owner/business/profile?tenant_id=tenant_demo" \
  -H "Authorization: Bearer ${VOZ_OWNER_API_KEY}"

curl -sS -X DELETE "http://localhost:8000/owner/business/profile?tenant_id=tenant_demo" \
  -H "Authorization: Bearer ${VOZ_OWNER_API_KEY}"
```

## Expected response shape
- GET:
  - `{"ok": true, "tenant_id": "...", "profile": {...}|null}`
- PUT:
  - `{"ok": true, "tenant_id": "...", "event_id": "...", "profile": {...}}`
- DELETE:
  - `{"ok": true, "tenant_id": "...", "event_id": "...", "deleted": true}`

