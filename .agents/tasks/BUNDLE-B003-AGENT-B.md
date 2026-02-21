# BUNDLE-B003 — Agent B (Backend/Notifications/Inbox Actions)

## Tasks
- `TASK-0243`: Postcall extraction v2 fields.
- `TASK-0244`: Email notifications (owner, idempotent).
- `TASK-0245`: Owner inbox actions API.

## File scope (exclusive)
- `features/postcall_extract.py`
- `features/postcall_notify_email.py`
- `features/owner_inbox_actions.py`
- corresponding tests
- ops reference-pack writeback for touched features

## Must verify
- Run postcall and notification idempotency checks.
- Provide DB/event evidence commands if direct verification unavailable.

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
