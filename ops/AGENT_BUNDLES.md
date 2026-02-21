# Agent Bundles (3-At-All-Times)

**Updated:** 2026-02-21 (America/New_York)

## Bundle B001 (Executed 2026-02-20)

Command:
- `bash scripts/agent_bundle_workflow.sh execute B001`
- Proof-gate checklist:
  - `bash scripts/bundle_gate_checklist.sh B001`
  - `ops/BUNDLE_PROOF_GATES.md`

### Agent A — Runtime Voice
- Task: `TASK-0401`
- Status: DONE
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
- Status: DONE
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
- Status: DONE
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

## Mandatory Delivery Contract (All Agents)
- Every agent output must include:
  1. `Verification Commands` (copy/paste runnable)
  2. `Expected Output Signatures`
  3. `Render Env Changes Required` (exact var/value updates or confirms)
- For API/backend tasks, verification must include at least one curl against the changed endpoint(s).
- For persistence/event tasks, verification must include DB evidence (query endpoint or sqlite/sql check).
- If the agent cannot run a check, it must provide `OPERATOR-RUN` commands and expected signatures.

## Bundle B005 (Ready)

Command:
- `bash scripts/agent_bundle_workflow.sh execute B005`

Focus:
- Intent/NLU hardening off hot path
- Owner/auth/event API hardening
- Portal auth/tenant guardrails

## Bundle B006 (Ready)

Command:
- `bash scripts/agent_bundle_workflow.sh execute B006`

Focus:
- Customer vertical flows (restaurant orders + barber appointments)
- Deterministic backend modules + idempotent notifications
- Portal order/appointment operations UI

## Bundle B007 (Ready)

Command:
- `bash scripts/agent_bundle_workflow.sh execute B007`

Focus:
- Owner analytics voice handoff
- Dynamic skill engine (DB + web/api adapters behind flags)
- Portal skill studio and run controls

## Bundle B008 (Ready)

Command:
- `bash scripts/agent_bundle_workflow.sh execute B008`

Focus:
- Voice runtime hardening (barge-in + fragmented speech tuning)
- Quality workers (regression/security/capacity) and report outputs
- Portal release checks + operator runbooks
