# BUNDLE-B005 — Agent A (Voice Intent/NLU Hardening)

## Tasks
- `TASK-0260`: Add off-hot-path NLU classifier hook on `transcript_completed` (never in 20ms sender loop).
- `TASK-0261`: Emit deterministic intent fields: `intent_name`, `intent_confidence`, `intent_source=nlu|heuristic`.
- `TASK-0262`: Add threshold policy and fallback (`high=emit`, `medium=review`, `low=heuristic`).

## File scope (exclusive)
- `features/voice_flow_a.py`
- `tests/test_voice_flow_a.py`

## Must verify
- No additional per-frame work in Twilio sender/audio loop.
- Intent pipeline runs only after transcript completion events.

## Required checks
- `ruff check features/voice_flow_a.py tests/test_voice_flow_a.py`
- `python3 -m py_compile features/voice_flow_a.py tests/test_voice_flow_a.py`
- `.venv/bin/python -m pytest -q tests/test_voice_flow_a.py`

## Mandatory Delivery Contract
- Include a `Verification Commands` section with copy/paste commands actually run (or to run if blocked):
  - curl commands (when HTTP/API behavior is touched)
  - DB verification commands (sqlite/sql or endpoint reads) when persistence is touched
  - lint/typecheck/test commands with exit status
- Include an `Expected Output Signatures` section for each verification command.
- Include a `Render Env Changes Required` section listing exact variable names/values to set or confirm.
- If unable to execute a verification command, mark `OPERATOR-RUN` and still provide exact command + expected signature.
