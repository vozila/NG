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

What was added:
- `WaitingAudioController` integrated into Flow A WS path with an aux lane concept.
- Chime default remains OFF: `VOICE_WAIT_CHIME_ENABLED=0`.
- Tests added to ensure aux does not interfere with main lane and barge-in stops aux immediately.

Why:
- We explicitly do NOT want “thinking sounds” to fight assistant speech buffers or barge-in.
- Two lanes + simple precedence rules are safer than mixing audio sources.

Next:
- Implement OpenAI Realtime bridge as main lane source (flagged).
- Add deterministic pacing and backlog caps for outbound audio.

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

## 2026-02-18 — TASK-0201.5 Flow A audible speech (Realtime audio out)

Outcome:
- Confirmed end-to-end audible assistant speech on the shared line.
- OpenAI Realtime emitted `response.output_audio.delta` and Twilio received paced μ-law frames.

Key learning (root cause of prior “no audio deltas”):
- The Realtime server rejected `response.modalities=['audio']` with `invalid_value`.
- Supported combinations were `['text']` and `['audio','text']`.
- Fix: request `['audio','text']` (ideally driven from `session.output_modalities`).

Evidence (≤5 log lines):
- `OPENAI_RESPONSE_CREATE_SENT rid=1 modalities=['audio', 'text']`
- `OPENAI_RESPONSE_CREATED id=resp_DAjQJUH46ITierNlCpbeU`
- `OPENAI_AUDIO_DELTA_FIRST response_id=resp_DAjQJUH46ITierNlCpbeU bytes=800`
- `TWILIO_MAIN_FRAME_SENT first=1 response_id=resp_DAjQJUH46ITierNlCpbeU bytes=160 q_main=4`
- Caller heard synthesized speech.

Rollback:
- `VOZ_FLOW_A_OPENAI_BRIDGE=0` disables OpenAI bridge (Twilio stream still works).

## 2026-02-18 — Added dual-mode requirement (client vs owner)

New requirement:
- Each tenant supports two interaction modes:
  - `actor_mode=client` (customer-facing protocol + customer-only capabilities)
  - `actor_mode=owner` (owner protocol + analytics/admin capabilities)

Plan updates:
- Build plan updated to include access-code → `{tenant_id, actor_mode}` routing and mode-aware feature/skill gating.
- Taskboard updated with achieved Flow A audio output and next tasks for dual-mode access + policy enforcement.

Quality gates (local ZIP snapshot):
- compileall ✅
- ruff ✅
- pytest ✅
