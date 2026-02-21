# BUNDLE-B007 — Agent A (Voice Owner Analytics Handoff)

## Tasks
- `TASK-0280`: Add owner-mode analytics query intent route from voice turns to out-of-band analytics executor.
- `TASK-0281`: Add short spoken response contract (summary + optional follow-up prompt).
- `TASK-0282`: Emit analytics trace events with correlation IDs for reproducibility.

## File scope (exclusive)
- `features/voice_flow_a.py`
- `tests/test_voice_flow_a.py`

## Must verify
- Hot path remains thin; analytics query execution remains off-loop.
- Spoken response stays concise to avoid monologue/barge-in churn.

## Required checks
- `ruff check features/voice_flow_a.py tests/test_voice_flow_a.py`
- `python3 -m py_compile features/voice_flow_a.py tests/test_voice_flow_a.py`
- `.venv/bin/python -m pytest -q tests/test_voice_flow_a.py`

## Mandatory Delivery Contract
- Include `Verification Commands`, `Expected Output Signatures`, `Render Env Changes Required`, and `OPERATOR-RUN` when blocked.
