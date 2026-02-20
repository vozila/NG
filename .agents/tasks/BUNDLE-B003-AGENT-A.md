# BUNDLE-B003 — Agent A (Voice/Telephony)

## Tasks
- `TASK-0240`: In-call callback/appointment intent capture events.
- `TASK-0241`: “Talk to owner” flow baseline.
- `TASK-0242`: Optional customer SMS follow-up capability (idempotent).

## File scope (exclusive)
- `features/voice_flow_a.py`
- `tests/test_voice_flow_a.py`

## Must verify
- Review `ops/logs/*` for intent events and barge-in/audio stability.
- If unable to verify directly, provide commands + expected signatures.

## Required checks
- `ruff check features/voice_flow_a.py tests/test_voice_flow_a.py`
- `python3 -m py_compile features/voice_flow_a.py tests/test_voice_flow_a.py`
- `.venv/bin/python -m pytest -q tests/test_voice_flow_a.py`

