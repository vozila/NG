# Vozlia NG — Build Plan (Living)

**Updated:** 2026-02-18 (America/New_York)

This plan is optimized for parallel agent execution while protecting Flow A reliability and preventing drift.

---

## 0) Objective

Ship a stable Vozlia NG foundation where:
- **Flow A voice** is rock-solid and hot-path safe
- features are modular, self-registering, and kill-switched
- **every tenant supports two interaction modes** (client-facing vs business-owner-facing)
- owner analytics are **DB-derived and auditable**
- regressions/security/capacity failures are loud and automated
- continuity lives in `ops/*` (repo-backed memory spine)

---

## 1) Monorepo layout (target)

We will evolve NG into a single monorepo containing:

```
NG/
  backend/          # FastAPI runtime + feature loader + features/*
  control_plane/    # provisioning, tenant admin, billing orchestration
  webui/            # Next.js owner portal + config UI
  ops/              # decisions, journal, taskboard, quality reports, reference packs
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
- Mode routing (client vs owner)

Blocked by core DB/event store scaffold (Core Maintainer batch):
- KB ingestion persistence
- Restaurant orders persistence
- Barbershop appointments persistence
- Owner analytics
- Dynamic DB skills persistence
- Notifications (depends on order/appointment events + contact model)

---

## 3) Tenant interaction modes (client vs business owner)

### Why this is mandatory
Each tenant/customer must support **two modes** with different behavior and permissions:

1) **Client-facing mode** (customer/caller)
- Business greeting + customer protocol
- Customer-facing skills (order placing, appointment requests, FAQs)
- Strictly **no business analytics** / owner-only operations

2) **Business-owner mode**
- Owner-facing greeting + owner protocol
- Business analytics / “ask anything about my business” (DB-derived, auditable)
- Administrative controls (future: hours, routing toggles, notification policies)

### Canonical names
- `actor_mode`: `"client"` | `"owner"` (this is the mode enforced by policy)
- `tenant_mode`: `"shared"` | `"dedicated"` (this is the line routing mode)

### Access gate requirements (shared number)
The shared number access gate must:
- Prompt generically (no “business access code” wording):
  - “Please enter your 8-digit access code.”
- Resolve access code → `{tenant_id, actor_mode}`
- Start the Twilio Media Stream with **both**:
  - `tenant_id=<tenant>`
  - `actor_mode=<client|owner>`
  - (plus existing `tenant_mode=shared` and `rid=<CallSid>`)

#### Configuration surface (MVP via env vars)
Preferred single-table config:
- `VOZ_ACCESS_CODE_TABLE_JSON` (JSON map)
  - `{ "12345678": {"tenant_id":"tenant_demo","actor_mode":"owner"}, "87654321":{"tenant_id":"tenant_demo","actor_mode":"client"} }`

Back-compat option (while migrating):
- `VOZ_ACCESS_CODE_MAP_JSON` (existing) treated as `"owner"` codes
- `VOZ_CLIENT_ACCESS_CODE_MAP_JSON` (new) treated as `"client"` codes
- Access gate merges both maps into a single resolver (conflicts fail closed).

### Mode-aware protocol selection (MVP)
At minimum, Flow A must select **instructions/persona** by `(tenant_id, actor_mode)` without heavy work in the audio loop.

Recommended env config:
- `VOZ_TENANT_MODE_POLICY_JSON` (JSON)
  - per tenant, per mode:
    - `openai_instructions` (short, mode-specific)
    - `greeting_style` / disclosure snippet (voice)
    - `feature_allowlist` or `feature_blocklist` (optional)
    - `skill_allowlist` or `skill_blocklist` (optional; enforced by router later)

Safe defaults:
- If `actor_mode` is missing/unknown: treat as `"client"` and deny owner-only operations.
- If a policy entry is missing: fall back to tenant defaults and keep conservative capabilities.

### Mode-aware feature/skill gating (MVP and beyond)

**MVP rule:** every feature/skill must declare what modes it is allowed to run in, and enforcement must fail closed.

Practical MVP knobs (env-only; no DB required):
- Per-feature modes:
  - `VOZ_FEATURE_<NAME>_MODES="client,owner"` (default both unless explicitly restricted)
- (Optional) per-tenant override:
  - `VOZ_TENANT_FEATURE_MODES_JSON` for tenant-specific exceptions

Enforcement points (in order of priority):
1) **Access gate** sets `actor_mode` deterministically.
2) **Voice Flow A** applies mode-specific instructions and blocks owner-only intents when in client mode.
3) **Skill router (future)** enforces allowlists before executing any skill.

Examples:
- `business_analytics`: owner-only
- `order_placing`, `customer_greeting`, `order_notification`: client-only
- `call_summary`, `missed_call_capture`: both

---

## 4) Flow A: OpenAI Realtime bridge port (hot-path safe)

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
- Deterministic routing decisions based on call metadata:
  - `tenant_id`, `tenant_mode`, `actor_mode`, `rid`

### Known Realtime compatibility gotcha (must remember)
Some OpenAI Realtime servers/models reject `response.modalities=['audio']` and only support:
- `['text']`
- `['audio','text']`

**Therefore:** `response.create` must request the **supported** combination, ideally using `session.output_modalities` (or defaulting to `['audio','text']`).

---

## 5) Thinking chime: design spec (must not regress barge-in)

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

## 6) DB/analytics: “ask anything” metrics without prewritten queries

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

## 7) Repo continuity: memory spine (non-optional)

Canonical continuity lives in-repo:
- `ops/CHECKPOINT.md` (current state / last known good / next actions)
- `ops/JOURNAL.md` (append-only session entries)
- `ops/DECISIONS.md` (dated decisions + implications)
- `ops/KNOWN_GOTCHAS.md` (pitfalls + fixes)
- `ops/REFERENCE_PACKS/voice_flow_a.md` (Flow A golden behavior + failure signatures)

Rule:
- For Flow A/streaming/barge-in/transcript routing work: **update the relevant REFERENCE_PACK first**.

---

## 8) Next tasks to create

Create tasks under `.agents/tasks/` (one task = one file change set):

1) TASK-0203: Dual-mode access codes (client vs owner) in shared line access gate
   - Generic prompt
   - Code resolver returns `{tenant_id, actor_mode}`
   - Stream customParameters include actor_mode

2) TASK-0204: Mode policy enforcement (MVP env-only)
   - Mode-specific instructions by `(tenant_id, actor_mode)`
   - Per-feature modes: `VOZ_FEATURE_<NAME>_MODES`
   - Fail-closed on unknown modes

3) TASK-0205: Owner-mode analytics foundations (blocked by DB/event store readiness)
   - QuerySpec schema + deterministic executor
   - Owner-only by policy

4) TASK-0206: Client-mode capabilities (MVP)
   - Customer greeting + customer protocols
   - Order/appointment request capture (domain stubs acceptable)

5) TASK-0300 (Core Maintainer): Event store + DB scaffold (if not already merged)
6) TASK-0301: Analytics owner Q&A query spec + safe executor (blocked by DB)
