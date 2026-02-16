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
