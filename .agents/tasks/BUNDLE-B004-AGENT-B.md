# BUNDLE-B004 — Agent B (Goals/Playbooks/Scheduler Backend)

## Tasks
- `TASK-0253`: Goals persistence + lifecycle.
- `TASK-0254`: Portal chat wizard (schema-validated).
- `TASK-0255`: Scheduler tick + execution runner MVP.

## File scope (exclusive)
- `features/wizard_goals.py`
- `features/playbooks.py`
- `features/scheduler_tick.py`
- corresponding tests
- ops reference-pack + memory-spine writeback for touched domains

## Must verify
- Run scheduler tick path with deterministic evidence.
- If direct verification unavailable, provide exact curl + expected payloads.

## Required checks
- `ruff check` on touched feature/test files.
- `python3 -m py_compile` on touched feature/test files.
- targeted pytest for touched features.

## Mandatory Delivery Contract
- Include a `Verification Commands` section with copy/paste commands actually run (or to run if blocked):
  - curl commands (when HTTP/API behavior is touched)
  - DB verification commands (sqlite/sql or endpoint reads) when persistence is touched
  - lint/typecheck/test commands with exit status
- Include an `Expected Output Signatures` section for each verification command.
- Include a `Render Env Changes Required` section listing exact variable names/values to set or confirm.
- If unable to execute a verification command, mark `OPERATOR-RUN` and still provide exact command + expected signature.
