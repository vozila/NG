# BUNDLE-B001 — Agent A Instructions

Read this file before starting.

## Task
- Primary task: `TASK-0401`
- Task spec: `.agents/tasks/TASK-0401.md`

## Scope (exclusive)
- `features/voice_flow_a.py`
- `tests/test_voice_flow_a.py`

## Must do
1. Implement only runtime voice hot-path changes for chunk-mode pacing parity.
2. Review latest Render logs in `ops/logs/` when voice event signatures are expected.
3. Update `.agents/tasks/TASK-0401.md` status and evidence notes.

## Must run checks
- `ruff check features/voice_flow_a.py tests/test_voice_flow_a.py`
- `python3 -m py_compile features/voice_flow_a.py tests/test_voice_flow_a.py`
- `.venv/bin/python -m pytest -q tests/test_voice_flow_a.py`

## Must not edit
- `scripts/*`
- `ops/*` (except adding referenced log filenames in task evidence if requested)
- Other active task files.

## Mandatory Delivery Contract
- Include a `Verification Commands` section with copy/paste commands actually run (or to run if blocked):
  - curl commands (when HTTP/API behavior is touched)
  - DB verification commands (sqlite/sql or endpoint reads) when persistence is touched
  - lint/typecheck/test commands with exit status
- Include an `Expected Output Signatures` section for each verification command.
- Include a `Render Env Changes Required` section listing exact variable names/values to set or confirm.
- If unable to execute a verification command, mark `OPERATOR-RUN` and still provide exact command + expected signature.
