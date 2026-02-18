# Vozlia NG — JOURNAL (append-only)

## 2026-02-15 — Day 0 scaffolding
- Goal: repo skeleton + loader + regression endpoint + sample feature.
- Known issue: ensure `ruff` is installed in dev/CI so `python -m ruff check .` runs.
- Next: run quality gates and capture ≤5 lines evidence into this journal.
## 2026-02-15 — Day 1 merges (Voice + Access + WhatsApp)

Merged into `main` (merge commits):
- TASK-0101 access gate: `6b7c9e5`
- TASK-0102 WhatsApp inbound: `f76748e`
- TASK-0100 Voice Flow A skeleton: `9a547a4`

New feature flags (default OFF):
- `VOZ_FEATURE_ACCESS_GATE`
- `VOZ_FEATURE_WHATSAPP_IN`
- `VOZ_FEATURE_VOICE_FLOW_A`

Quality evidence (post-merge):
- compileall ✅
- ruff ✅
- pytest ✅ (11 tests)
- regression ✅ status ok (writes `ops/QUALITY_REPORTS/latest_regression.json`; do not auto-commit updates)

Automation:
- `bash scripts/run_gates_record.sh` produces uploadable log + summary + timestamped regression snapshot.
- `bash scripts/clean_generated.sh` reverts rolling report + clears caches for clean commits.
- `bash scripts/merge_with_gates.sh <branch> "<merge message>"` merges + runs gates + pushes.

## 2026-02-17 — Flow A waiting/thinking audio lane (anti-regression foundation)
Context:
- Prior attempts to “inject a thinking chime” into the main outbound assistant buffer caused regressions
  (cancel/clear semantics, barge-in, buffers fighting each other).
Decision implemented:
- Treat thinking audio as a first-class state with a *separate aux audio lane*.
- Add a deterministic, unit-tested state machine (`WaitingAudioController`) that:
  - starts THINKING after a trigger threshold
  - enqueues a periodic chime into the aux buffer only when due
  - stops immediately on user speech (clears aux only) and suppresses until wait_end()
Code touched:
- `features/voice_flow_a.py`: added aux lane + sender loop scaffold + mu-law chime precompute.
- `tests/test_voice_flow_a.py`: added deterministic waiting-audio and lane-priority tests.
Quality evidence:
- compileall ✅
- pytest ✅ (16 tests)
Note:
- `ruff` is not installed in the current execution environment used to generate this patch.
  Repo gates should still run `python -m ruff check .` in CI/dev.

## 2026-02-17 — Shared line access + tenant routing for Twilio inbound
What was added:
- New feature module: `features/shared_line_access.py`.
- New Twilio Voice webhooks:
`POST /twilio/voice` (entry routing) and `POST /twilio/voice/access-code` (DTMF gather callback).
- Dedicated line behavior: route by `To` and return `<Connect><Stream ...>` immediately.
- Shared demo line behavior: prompt for 8-digit access code, validate, bounded retries, then connect stream.
- Stream custom params now include tenant metadata and request id:
`tenant_id`, `tenant_mode`, `rid`.
- Flow A update in `features/voice_flow_a.py`: parse `start.customParameters` for
`tenant_id`, `tenant_mode`, and `rid`, store in in-memory call/session context, log only under debug.

Flags/env vars:
- Feature flag (default OFF): `VOZ_FEATURE_SHARED_LINE_ACCESS=0`.
- Config vars:
`VOZ_DEDICATED_LINE_MAP_JSON`,
`VOZ_SHARED_LINE_NUMBER`,
`VOZ_ACCESS_CODE_MAP_JSON`,
optional `VOZ_TWILIO_STREAM_URL` (must be `wss://...`, defaults to `wss://example.invalid/twilio/stream`).
- Debug logging remains gated behind `VOZLIA_DEBUG=1`.

Endpoints:
- `POST /twilio/voice`
- `POST /twilio/voice/access-code`
- Existing WS endpoint remains `WS /twilio/stream`.

Rollback instruction:
- Set `VOZ_FEATURE_SHARED_LINE_ACCESS=0` to disable routing feature and unmount routes.
- If Twilio webhook was repointed to `/twilio/voice`, repoint it back to the previous handler.

## 2026-02-18 — TASK-0200 core DB event store scaffold
What was added:
- New module `core/db.py` with SQLite DB bootstrap (`VOZ_DB_PATH`, default `ops/vozlia_ng.sqlite3`), idempotent schema init, and tenant-scoped event APIs: `emit_event(...)` and `query_events(...)`.
- Schema includes `tenants` and canonical append-only `events` (`event_id`, `tenant_id`, `rid`, `event_type`, `ts`, `payload_json`, `trace_id`, `idempotency_key`) plus indexes on `(tenant_id, ts)` and `(tenant_id, event_type, ts)`.
- New tests in `tests/test_db_event_store.py` for schema creation, insert/query, tenant isolation, and idempotency-key behavior.

Env vars:
- `VOZ_DB_PATH` (default `ops/vozlia_ng.sqlite3`; dev fallback can be `:memory:`).

Rollback notes:
- Keep DB layer dormant by not importing/calling it from feature hot paths until explicitly enabled.
- For non-persistent local runs, set `VOZ_DB_PATH=:memory:`.
- Revert the task commit or stop calling `core.db` APIs (no migrations introduced).
