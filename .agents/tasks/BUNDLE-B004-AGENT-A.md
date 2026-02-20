# BUNDLE-B004 — Agent A (Voice/Telephony)

## Tasks
- `TASK-0250`: Owner voice goal-intake event.
- `TASK-0251`: Owner voice list-goals readout (short).
- `TASK-0252`: Owner voice pause/resume single goal.

## File scope (exclusive)
- `features/voice_flow_a.py`
- `tests/test_voice_flow_a.py`

## Must verify
- Confirm no heavy planning work is introduced in WS/audio hot path.
- If direct verification unavailable, provide operator commands and expected event signatures.

## Required checks
- `ruff check features/voice_flow_a.py tests/test_voice_flow_a.py`
- `python3 -m py_compile features/voice_flow_a.py tests/test_voice_flow_a.py`
- `.venv/bin/python -m pytest -q tests/test_voice_flow_a.py`

