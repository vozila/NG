# Reference Pack — OCR Ingest (Schema-First, Pending Review)

## Feature flag + auth
- `VOZ_FEATURE_OCR_INGEST=1`
- `VOZ_OWNER_OCR_INGEST_ENABLED=1` (optional runtime gate, default enabled)
- `VOZ_OWNER_API_KEY=<secret>`

## Endpoints
- `POST /owner/ocr/ingest`
- `GET /owner/ocr/reviews?tenant_id=<tenant>&limit=<n>`
- `POST /owner/ocr/reviews/{review_id}?tenant_id=<tenant>`

## Canonical curl commands
```bash
curl -sS -X POST 'http://localhost:8000/owner/ocr/ingest' \
  -H "Authorization: Bearer ${VOZ_OWNER_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "tenant_id":"tenant_demo",
    "source_name":"insurance_card.png",
    "raw_text":"member id: A1234\ngroup: G1"
  }'

curl -sS "http://localhost:8000/owner/ocr/reviews?tenant_id=tenant_demo&limit=20" \
  -H "Authorization: Bearer ${VOZ_OWNER_API_KEY}"

curl -sS -X POST "http://localhost:8000/owner/ocr/reviews/<review_id>?tenant_id=tenant_demo" \
  -H "Authorization: Bearer ${VOZ_OWNER_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"decision":"approve","reviewer":"ops-1","notes":"looks good"}'
```

## Expected response shape
- ingest:
  - `{"ok": true, "event_id":"...", "record":{"review_id":"...","schema_version":"v1","status":"pending_review","proposed_fields":{...}}}`
- reviews list:
  - `{"ok": true, "tenant_id":"...", "items":[{"review_id":"...","status":"pending_review",...}]}`
- review decision:
  - `{"ok": true, "event_id":"...", "record":{"review_id":"...","decision":"approve|reject","schema_version":"v1",...}}`

