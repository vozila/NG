# BUNDLE-B008 — Agent A (Voice Runtime Hardening)

## Tasks
- `TASK-0290`: Finalize barge-in policy knobs (soft vs hard interruption windows) with deterministic state transitions.
- `TASK-0291`: Add fragmented-speech turn stitching knobs and tests (VAD commit tuning).
- `TASK-0292`: Add runtime safety counters/alerts for underruns and pacing drift with bounded logging.

## File scope (exclusive)
- `features/voice_flow_a.py`
- `tests/test_voice_flow_a.py`

## Must verify
- No regressions in audio quality under chunk mode default ON.
- Barge-in behavior matches configurable policy contract.

## Required checks
- `ruff check features/voice_flow_a.py tests/test_voice_flow_a.py`
- `python3 -m py_compile features/voice_flow_a.py tests/test_voice_flow_a.py`
- `.venv/bin/python -m pytest -q tests/test_voice_flow_a.py`

## Mandatory Delivery Contract
- Include `Verification Commands`, `Expected Output Signatures`, `Render Env Changes Required`, and `OPERATOR-RUN` when blocked.
