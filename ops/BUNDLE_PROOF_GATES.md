# Bundle Proof Gates (Detect Issues Early)

**Updated:** 2026-02-20 (America/New_York)

This document is the required verification contract for bundle execution.

## Global policy (all bundles)
1. Stop-the-line rule: if a hot-path voice regression is suspected, pause new feature work and run the bundle gate checks immediately.
2. Every active agent must do one of:
   - run the verification directly and attach evidence, or
   - provide exact copy/paste commands for operator verification.
3. No bundle is marked complete until:
   - code checks pass,
   - API checks pass (where applicable),
   - DB/event evidence is captured (where applicable),
   - manual call checks are completed for voice-impacting work.

## Baseline checks (run every bundle)
```bash
python3 -m compileall .
ruff check .
```

If tests are available:
```bash
.venv/bin/python -m pytest -q
```

## Bundle 1 gate (access + dual-mode routing)

### API checks
```bash
# Shared-line access resolve (owner)
curl -sS -X POST "$BASE_URL/admin/access-codes/resolve" \
  -H "Authorization: Bearer $VOZ_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"code":"<OWNER_CODE>"}'

# Shared-line access resolve (customer)
curl -sS -X POST "$BASE_URL/admin/access-codes/resolve" \
  -H "Authorization: Bearer $VOZ_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"code":"<CUSTOMER_CODE>"}'

# Owner code view (tenant-scoped)
curl -sS "$BASE_URL/owner/access-codes?tenant_id=<TENANT_ID>" \
  -H "Authorization: Bearer $VOZ_OWNER_API_KEY"
```

### Event evidence checks
```bash
# Recent flow events
curl -sS "$BASE_URL/owner/events?tenant_id=<TENANT_ID>&limit=50" \
  -H "Authorization: Bearer $VOZ_OWNER_API_KEY"
```

Expected evidence:
- `flow_a.call_started.payload.ai_mode` present for owner and customer calls.
- Routing decision logs show resolved `ai_mode`.

## Bundle 2 gate (profile/template/OCR + grounding)

### API checks
```bash
# Business profile CRUD smoke
curl -sS -X POST "$BASE_URL/owner/business-profile" \
  -H "Authorization: Bearer $VOZ_OWNER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"<TENANT_ID>","hours":"9-5","services":["cut"],"pricing":"from $30"}'

# OCR ingest (out-of-band)
curl -sS -X POST "$BASE_URL/owner/ocr/ingest" \
  -H "Authorization: Bearer $VOZ_OWNER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"<TENANT_ID>","image_base64":"<BASE64_FIXTURE>"}'
```

### Voice/manual checks
- Place a customer-mode call:
  - ask “what are your hours?”
  - ask “how much is a haircut?”
- Verify responses are grounded in profile/template and safe-language policy.

### Event evidence checks
Expected event:
- `flow_a.knowledge_context` with template key + profile version/hash.

## Bundle 3 gate (lead/appt + notifications + owner actions)

### API checks
```bash
# Post-call extract/reconcile
curl -sS -X POST "$BASE_URL/admin/postcall/reconcile" \
  -H "Authorization: Bearer $VOZ_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"<TENANT_ID>","limit":50,"dry_run":false}'

# Owner inbox actions
curl -sS -X POST "$BASE_URL/owner/inbox/actions" \
  -H "Authorization: Bearer $VOZ_OWNER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"<TENANT_ID>","rid":"<RID>","action":"mark_qualified"}'
```

### DB/event evidence checks
Use your DB query tooling to confirm idempotent writes:
- no duplicate `notify.sms_sent`/email sent markers for same `rid`,
- expected `postcall.*` artifacts present.

### Insights check
```bash
curl -sS "$BASE_URL/owner/insights/summary?tenant_id=<TENANT_ID>" \
  -H "Authorization: Bearer $VOZ_OWNER_API_KEY"
```

### Bundle 3 closeout checklist (portal integration)
Preflight env (portal):
- `VOZLIA_CONTROL_BASE_URL`
- `VOZLIA_ADMIN_KEY`
- `NEXTAUTH_URL`
- `NEXTAUTH_SECRET`

Preflight env/flags (backend where applicable):
- `VOZ_FEATURE_OWNER_INBOX=1`
- `VOZ_OWNER_INBOX_ENABLED=1`

Operator-run portal API checks (requires authenticated session cookie):
```bash
curl -sS "http://localhost:3000/api/admin/owner-inbox/leads?tenant_id=<TENANT_ID>&limit=5" \
  -H "Cookie: <session-cookie>"

curl -sS -X POST "http://localhost:3000/api/admin/owner-inbox/actions" \
  -H "Content-Type: application/json" \
  -H "Cookie: <session-cookie>" \
  -d '{"tenant_id":"<TENANT_ID>","rid":"<RID>","action":"qualify","payload":{"score":90,"notes":"qualified from UI"}}'

curl -sS -X POST "http://localhost:3000/api/admin/owner-inbox/actions" \
  -H "Content-Type: application/json" \
  -H "Cookie: <session-cookie>" \
  -d '{"tenant_id":"<TENANT_ID>","rid":"<RID>","action":"mark_handled","payload":{"handled":true,"handled_by":"owner_ui"}}'

curl -sS "http://localhost:3000/api/admin/owner-inbox/appt-requests?tenant_id=<TENANT_ID>&limit=5" \
  -H "Cookie: <session-cookie>"
```

Expected signatures:
- Leads/appt endpoints return JSON with `ok` and non-error payload.
- Actions endpoint returns success marker (`ok`/`success`) and no `4xx/5xx`.
- UI smoke: row transitions to qualified, then handled.

## Bundle 4 gate (goal wizard → playbook → scheduler)

### API checks
```bash
# Goal create/approve
curl -sS -X POST "$BASE_URL/owner/goals" \
  -H "Authorization: Bearer $VOZ_OWNER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"<TENANT_ID>","goal":"<GOAL_TEXT>"}'

# Scheduler tick
curl -sS -X POST "$BASE_URL/admin/scheduler/tick" \
  -H "Authorization: Bearer $VOZ_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"<TENANT_ID>"}'
```

### Verification outcome
- execution logs emitted,
- notification delivered once,
- goal edit updates next run/policy as expected.

## Agent evidence format (required)
- Commands run:
- Key outputs:
- Log files reviewed (`ops/logs/...`):
- Pass/Fail:
- If not run by agent: exact commands provided to operator.
