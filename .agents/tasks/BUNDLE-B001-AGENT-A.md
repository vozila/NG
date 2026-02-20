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
