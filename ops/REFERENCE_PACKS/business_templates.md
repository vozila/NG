# Reference Pack — Business Templates v1

## Feature flag + auth
- `VOZ_FEATURE_BUSINESS_TEMPLATES=1`
- `VOZ_OWNER_API_KEY=<secret>`
- Optional catalog override:
  - `VOZ_BUSINESS_TEMPLATES_JSON='[{"template_id":"x","label":"X","instructions":"..."}]'`

## Endpoints
- `GET /owner/business/templates/catalog`
- `GET /owner/business/templates/current?tenant_id=<tenant>`
- `PUT /owner/business/templates/current`

## Canonical curl commands
```bash
curl -sS "http://localhost:8000/owner/business/templates/catalog" \
  -H "Authorization: Bearer ${VOZ_OWNER_API_KEY}"

curl -sS "http://localhost:8000/owner/business/templates/current?tenant_id=tenant_demo" \
  -H "Authorization: Bearer ${VOZ_OWNER_API_KEY}"

curl -sS -X PUT 'http://localhost:8000/owner/business/templates/current' \
  -H "Authorization: Bearer ${VOZ_OWNER_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "tenant_id":"tenant_demo",
    "template_id":"front_desk_general_v1",
    "custom_instructions":"Keep answers under 20 words."
  }'
```

## Expected response shape
- catalog:
  - `{"ok": true, "version": "v1", "templates": [{"template_id":"...","label":"...","instructions":"..."}]}`
- current:
  - `{"ok": true, "tenant_id":"...", "selection":{"template_id":"...","label":"...","instructions":"...","custom_instructions":"..."|null}}`

