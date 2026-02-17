# Vozlia NG — CONTEXT

This file is the **living crosswalk** between legacy repos (read-only reference) and NG.

---

## Legacy repo map (reference-only)

- **vozlia-backend**
  - runtime FastAPI + Twilio WS `/twilio/stream`
  - contains legacy Flow A OpenAI Realtime bridge (`flow_a.py`)
  - contains Flow B/other pipelines (reference only)

- **vozlia-admin**
  - Next.js admin UI (owner-facing controls)

- **Front-end**
  - Python control-plane style service (KB ingest, wizard/config services, admin endpoints)

---

## NG repo reality (today)

NG currently represents the **backend service** skeleton:
- `core/*` stable surface area
- `features/*` plugin-discovered feature modules (one-file rule)
- `ops/*` decision log, journal, taskboard, quality reports

Planned additions to satisfy the monorepo requirement:
- `webui/` (Next.js/React) — owner portal & config UI
- `control_plane/` (service or package) — provisioning + tenant admin + billing orchestration
  - NOTE: even if deployed as separate services later, they live in this monorepo.

---

## Crosswalk (legacy → NG)

### Voice Flow A
- Legacy: `vozlia-backend/flow_a.py`
- NG: `features/voice_flow_a.py` (must remain hot-path safe)

Porting goals:
- replicate OpenAI Realtime session config + audio bridge reliability
- add a **thinking chime** safely (env-flagged)
- keep planning/tool execution out of the WS loop

### Shared line / access gate
- NG: `features/access_gate.py`
- Future integration:
  - shared line → access gate → tenant routing decision → Flow A session metadata

### KB ingestion / control plane services
- Legacy: `Front-end/kb_ingest.py`, `kb_query.py`, workers, etc.
- NG: future `features/kb_ingestion.py` + core persistence primitives (Core Maintainer)

---

## Operational invariants recap

- One-file feature modules; no cross-feature imports
- Debug logs only when `VOZLIA_DEBUG=1`
- Features default OFF behind `VOZ_FEATURE_*`
- Flow A hot path must stay deterministic and minimal

