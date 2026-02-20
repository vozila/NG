# BUNDLE-B002 — Agent A (Voice/Telephony)

## Tasks
- `TASK-0230`: Customer-mode prompt uses business profile + template.
- `TASK-0231`: Customer-safe language + escalation baseline.
- `TASK-0232`: Emit `flow_a.knowledge_context` event.

## File scope (exclusive)
- `features/voice_flow_a.py`
- `tests/test_voice_flow_a.py`

## Must verify
- Review `ops/logs/*` for knowledge-context and no hot-path regressions.
- If unable to verify directly, provide operator commands and expected signatures.

## Required checks
- `ruff check features/voice_flow_a.py tests/test_voice_flow_a.py`
- `python3 -m py_compile features/voice_flow_a.py tests/test_voice_flow_a.py`
- `.venv/bin/python -m pytest -q tests/test_voice_flow_a.py`

