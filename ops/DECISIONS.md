# Vozlia NG — DECISIONS

## 2026-02-15 — Day 0
- One-file feature modules in `features/` with `FEATURE` contract.
- Feature flags default OFF via `VOZ_FEATURE_<NAME>`.
- Regression runner report written to `ops/QUALITY_REPORTS/latest_regression.json`.
## 2026-02-15 — Day 1
- Voice “thinking audio” mitigation: Flow A will use explicit waiting hooks and later a separate aux audio lane to avoid fighting barge-in + buffers. Initial waiting hooks are included in TASK-0100.
- Evidence policy: `ops/QUALITY_REPORTS/latest_regression.json` is committed for Day 0 baseline only. Subsequent gate runs should snapshot to timestamped files (log + regression snapshot) and avoid committing the rolling report unless explicitly requested.
- Automation: prefer `scripts/run_gates_record.sh` for uploadable logs; `scripts/clean_generated.sh` to keep feature branches clean.
