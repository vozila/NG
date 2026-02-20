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

