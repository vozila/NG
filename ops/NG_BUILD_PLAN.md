# Vozlia NG — Build Plan (Living)

**Updated:** 2026-02-17 (America/New_York)

This plan is optimized for parallel agent execution while protecting Flow A reliability.

---

## 0) Objective

Ship a stable Vozlia NG foundation where:
- **Flow A voice** is rock-solid and hot-path safe
- features are modular and self-registering
- owner analytics are **DB-derived and auditable**
- regressions/security/capacity failures are loud and automated

---

## 1) Monorepo layout (target)

We will evolve NG into a single monorepo containing:

```
NG/
  backend/          # FastAPI runtime + feature loader + features/*
  control_plane/    # provisioning, tenant admin, billing orchestration
  webui/            # Next.js owner portal + config UI
  ops/              # decisions, journal, taskboard, quality reports
```

**Transitional approach (recommended):**
- Keep the current Python service as the backend codebase for now.
- Add `webui/` and `control_plane/` directories next.
- When ready, migrate the backend package into `backend/` with minimal diffs.

---

## 2) Dependency graph (blocked items)

Unblocked:
- Flow A OpenAI Realtime port (feature-only)

Depends on Flow A metadata capture + access gate alignment:
- Tenant routing (shared vs dedicated)

Blocked by core DB/event store scaffold (Core Maintainer batch):
- KB ingestion persistence
- Restaurant orders persistence
- Barbershop appointments persistence
- Owner analytics
- Dynamic DB skills persistence
- Notifications (depends on order/appointment events + contact model)

---

## 3) Flow A: OpenAI Realtime bridge port (hot-path safe)

### Goals
- Port legacy OpenAI Realtime bridge behavior to NG `features/voice_flow_a.py`
- Preserve barge-in correctness and avoid buffer regressions
- Keep planning/tool execution out-of-band

### Hot-path rules
- No DB reads in WS loop
- No JSON logging per audio frame
- No expensive transforms per frame (precompute where possible)

### Required behaviors
- Twilio WS receives `start`/`media`/`stop`
- OpenAI Realtime session config:
  - g711_ulaw in/out
  - server_vad; interrupt_response true
- Deterministic routing decisions based on call metadata

---

## 4) Thinking chime: design spec (must not regress barge-in)

**Problem:** when the assistant is waiting on LLM/tool work, callers perceive silence.

### Spec
- When the system is in a “waiting” state for > `VOICE_WAIT_SOUND_TRIGGER_MS`:
  - emit a short chime every `VOICE_WAIT_CHIME_EVERY_MS`
- Stop chime immediately when:
  - caller speech starts (barge-in)
  - assistant audio begins
  - call ends

### Constraints
- Chime audio MUST be deterministic server-injected audio (not LLM output).
- Chime must be env-flagged OFF by default.

### Proposed env flags
- `VOICE_WAIT_CHIME_ENABLED=0|1` (default 0)
- `VOICE_WAIT_SOUND_TRIGGER_MS=800` (existing)
- `VOICE_WAIT_CHIME_EVERY_MS=1200`
- `VOICE_WAIT_CHIME_MAX_SECONDS=30` (safety)

### Implementation approach (recommended)
- Precompute (or embed) a μ-law 8kHz short tone buffer.
- Output mux logic:
  - assistant audio has priority
  - chime only emits when assistant queue is empty and waiting flag active
- Use Twilio `clear` on barge-in to drop queued audio and stop chime.

---

## 5) DB/analytics: “ask anything” metrics without prewritten queries

### Requirement
Owners must be able to ask natural language metrics questions and receive:
- accurate numbers
- derived deterministically from DB
- with audit trail

### Architecture (recommended)
1) **Canonical event store** (`events` table) for all domain interactions:
   - orders, appointments, calls, notifications, messages, KB updates
2) **Validated QuerySpec** (strict JSON schema) produced by LLM:
   - metrics, dimensions, filters, time range, ordering, limit
3) **Deterministic SQL builder** in Python:
   - enforces tenant_id filter
   - enforces row limits & safe SELECT-only queries
   - uses schema introspection (information_schema) to map fields
4) **Skill persistence**
   - store validated QuerySpec as a “dynamic DB skill”
   - re-run on demand or on schedule

### Safety rails
- tenant isolation on every query
- max scan/rows caps
- explicit “I’m not sure” fallback when spec invalid

---

## 6) Repo continuity: running log

- `ops/JOURNAL.md` is append-only and is the canonical “what happened and why”.
- Every meaningful session/task must append:
  - what changed
  - key decision(s)
  - known issues
  - next actions

This reduces drift when chat context resets or new agents join.

---

## 7) Next tasks to create

Create tasks under `.agents/tasks/`:

1) TASK-0200: Port Flow A OpenAI Realtime bridge (feature-only)
2) TASK-0201: Add thinking chime injector behind env flags (feature-only)
3) TASK-0202: Tenant routing integration (access gate ↔ voice)
4) TASK-0300 (Core Maintainer): event store + DB scaffold
5) TASK-0301: analytics owner Q&A query spec + safe executor (blocked by DB)

