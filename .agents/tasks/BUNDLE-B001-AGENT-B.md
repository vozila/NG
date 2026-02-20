# BUNDLE-B001 — Agent B Instructions

Read this file before starting.

## Task
- Primary task: `TASK-0402`
- Task spec: `.agents/tasks/TASK-0402.md`

## Scope (exclusive)
- `scripts/capture_render_logs.sh`
- `scripts/analyze_bargein_latency.py`
- `scripts/extract_call_window.py`
- `ops/REFERENCE_PACKS/voice_flow_a.md`

## Must do
1. Harden logging/analysis workflow and preserve deterministic operator commands.
2. Review latest Render logs in `ops/logs/` and include concrete evidence output.
3. Update `.agents/tasks/TASK-0402.md` status and evidence notes.

## Must run checks
- `bash -n scripts/capture_render_logs.sh`
- `python3 -m py_compile scripts/analyze_bargein_latency.py scripts/extract_call_window.py`
- `ruff check scripts/analyze_bargein_latency.py scripts/extract_call_window.py`

## Must not edit
- `features/*`
- `tests/test_voice_flow_a.py`
- Memory-spine docs outside the reference pack listed above.
