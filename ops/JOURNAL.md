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

