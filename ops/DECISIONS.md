# Vozlia NG — DECISIONS

## 2026-02-15 — Day 0
- One-file feature modules in `features/` with `FEATURE` contract.
- Feature flags default OFF via `VOZ_FEATURE_<NAME>`.
- Regression runner report written to `ops/QUALITY_REPORTS/latest_regression.json`.
## 2026-02-15 — Day 1
- Voice “thinking audio” mitigation: Flow A will use explicit waiting hooks and later a separate aux audio lane to avoid fighting barge-in + buffers. Initial waiting hooks are included in TASK-0100.
- Evidence policy: `ops/QUALITY_REPORTS/latest_regression.json` is committed for Day 0 baseline only. Subsequent gate runs should snapshot to timestamped files (log + regression snapshot) and avoid committing the rolling report unless explicitly requested.
- Automation: prefer `scripts/run_gates_record.sh` for uploadable logs; `scripts/clean_generated.sh` to keep feature branches clean.

## 2026-02-17 — Flow A “thinking chime” as a first-class state (aux audio lane)
- We will NOT “inject” a chime into the same outbound buffer as assistant speech. Instead:
  - Maintain 2 independent outbound lanes:
    - main lane: assistant speech audio (OpenAI Realtime deltas)
    - aux lane: waiting/thinking comfort tone
  - Sender rule: always prefer main; only send aux when main is empty and thinking audio is active.
  - On barge-in / user speech while waiting: stop thinking audio immediately and clear only aux
    (do not clear/cancel main unless an actual assistant response is being canceled).
- Waiting/thinking audio activation is deterministic:
  - start WAIT when a tool/skill begins
  - after `VOICE_WAIT_SOUND_TRIGGER_MS` (default 800ms) enter THINKING and enable aux lane
  - stop immediately when the tool/skill completes
- Default safety posture:
  - `VOICE_WAIT_CHIME_ENABLED` defaults OFF; enable only after parity tests.
  - All waiting/chime logs remain gated behind `VOZLIA_DEBUG=1`.
- Implementation pattern:
  - `WaitingAudioController` is pure/deterministic and unit-tested.
  - Mu-law “beep frames” are precomputed once at import time to avoid hot-path CPU.

