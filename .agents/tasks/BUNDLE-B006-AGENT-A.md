# BUNDLE-B006 — Agent A (Voice Vertical Flows)

## Tasks
- `TASK-0270`: Customer-mode restaurant order-intake voice flow (guided capture + confirmation event emit).
- `TASK-0271`: Customer-mode barbershop appointment-intake voice flow (guided capture + confirmation event emit).
- `TASK-0272`: Add safe escalation prompts when required fields are missing or ambiguous.

## File scope (exclusive)
- `features/voice_flow_a.py`
- `tests/test_voice_flow_a.py`

## Must verify
- No heavy planning/DB scans in hot path.
- Deterministic event emission on transcript turn boundaries.

## Required checks
- `ruff check features/voice_flow_a.py tests/test_voice_flow_a.py`
- `python3 -m py_compile features/voice_flow_a.py tests/test_voice_flow_a.py`
- `.venv/bin/python -m pytest -q tests/test_voice_flow_a.py`

## Mandatory Delivery Contract
- Include `Verification Commands`, `Expected Output Signatures`, `Render Env Changes Required`, and `OPERATOR-RUN` when blocked.
