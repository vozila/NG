# Agent Bundles (3-At-All-Times)

**Updated:** 2026-02-20 (America/New_York)

## Bundle B001 (Active)

Command:
- `bash scripts/agent_bundle_workflow.sh execute B001`
- Proof-gate checklist:
  - `bash scripts/bundle_gate_checklist.sh B001`
  - `ops/BUNDLE_PROOF_GATES.md`

### Agent A — Runtime Voice
- Task: `TASK-0401`
- Owns only:
  - `features/voice_flow_a.py`
  - `tests/test_voice_flow_a.py`
- Must not edit:
  - `scripts/*`, `ops/*`, `.agents/tasks/TASK-0402.md`, `.agents/tasks/TASK-0403.md`
- Required checks:
  - `ruff check features/voice_flow_a.py tests/test_voice_flow_a.py`
  - `python3 -m py_compile features/voice_flow_a.py tests/test_voice_flow_a.py`
- Render-log review when expected:
  - verify `OPENAI_AUDIO_DELTA_FIRST`, `TWILIO_MAIN_FRAME_SENT`, `BARGE-IN*` signatures.

### Agent B — Tooling + Diagnostics
- Task: `TASK-0402`
- Owns only:
  - `scripts/capture_render_logs.sh`
  - `scripts/analyze_bargein_latency.py`
  - `scripts/extract_call_window.py`
  - `ops/REFERENCE_PACKS/voice_flow_a.md`
- Must not edit:
  - `features/*`, `tests/test_voice_flow_a.py`, memory-spine docs except reference pack above
- Required checks:
  - `bash -n scripts/capture_render_logs.sh`
  - `python3 -m py_compile scripts/analyze_bargein_latency.py scripts/extract_call_window.py`
  - `ruff check scripts/analyze_bargein_latency.py scripts/extract_call_window.py`
- Render-log review when expected:
  - run analyzer/extractor against `ops/logs/` and capture summary output.

### Agent C — Ops Scribe + Coordination
- Task: `TASK-0403`
- Owns only:
  - `AGENTS.md`
  - `ops/TASKBOARD.md`
  - `ops/CHECKPOINT.md`
  - `ops/JOURNAL.md`
  - `ops/DECISIONS.md`
  - `ops/AGENT_BUNDLES.md`
  - task status updates under `.agents/tasks/`
- Must not edit:
  - `features/*`, `tests/*`, runtime scripts
- Required checks:
  - consistency review of task status + active assignments
  - ensure each task file has objective/scope/checks/log-evidence sections
- Render-log review when expected:
  - link specific log files reviewed in `ops/JOURNAL.md` entries.

## Bundle execution protocol
1. One task/branch per agent.
2. No shared-file edits inside the same bundle.
3. Each agent updates its own `.agents/tasks/TASK-xxxx.md` status.
4. Each agent records checks run.
5. Agent C merges memory-spine updates only after A/B outputs are validated.
6. Bundle invocation phrase is standardized: `execute B00X` -> resolve via `scripts/agent_bundle_workflow.sh`.
7. If an agent cannot run a verification step, it must provide exact copy/paste commands and expected output signatures for operator execution.
