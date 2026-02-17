# Vozlia NG — DECISIONS

## 2026-02-15 — Day 0
- One-file feature modules in `features/` with `FEATURE` contract.
- Feature flags default OFF via `VOZ_FEATURE_<NAME>`.
- Regression runner report written to `ops/QUALITY_REPORTS/latest_regression.json`.

## 2026-02-15 — Day 1
- Voice “thinking audio” mitigation: Flow A will use explicit waiting hooks and later a separate aux audio lane to avoid fighting barge-in + buffers. Initial waiting hooks are included in TASK-0100.
- Evidence policy: `ops/QUALITY_REPORTS/latest_regression.json` is committed for Day 0 baseline only. Subsequent gate runs should snapshot to timestamped files (log + regression snapshot) and avoid committing the rolling report unless explicitly requested.
- Automation: prefer `scripts/run_gates_record.sh` for uploadable logs; `scripts/clean_generated.sh` to keep feature branches clean.

## 2026-02-17 — Rebuild alignment + new invariants
- Monorepo direction is locked: NG will contain **backend**, **control_plane**, and **webui** (legacy repos are reference-only).
- “Thinking chime” requirement is locked:
  - Chime must be deterministic server-injected audio (NOT LLM generated).
  - Chime must be barge-in safe: stop instantly when caller speaks or when assistant audio starts.
  - Chime must be env-flagged OFF by default and fully kill-switchable.
- Session continuity requirement is locked:
  - `ops/JOURNAL.md` is the canonical append-only log of major interactions/decisions.
  - Every meaningful session/task must append a short summary + next actions.
- Analytics/DB requirement is locked:
  - Owners must be able to ask metrics about “anything in the DB” without prewritten queries.
  - Implementation will be via: (1) canonical event store + (2) validated query spec → deterministic safe SQL execution → auditable result.
  - Dynamic DB skills persist the validated query spec for reuse/scheduling.

