# BUNDLE-B005 — Agent B (Owner/Auth/Event API Hardening)

## Tasks
- `TASK-0263`: Harden owner-event read APIs to fail closed with deterministic JSON on DB/storage faults (no raw 500 traceback leakage).
- `TASK-0264`: Enforce tenant binding model for owner APIs (prevent cross-tenant reads with shared owner key).
- `TASK-0265`: Add idempotency-key stability guardrails (no free-text expansion in keys).

## File scope (exclusive)
- `features/owner_events_api.py`
- `features/owner_insights.py`
- `features/owner_inbox_actions.py`
- `core/auth.py`
- related tests only
- `ops/REFERENCE_PACKS/owner_events_api.md` (if needed)

## Must verify
- Cross-tenant access attempts return deterministic deny response.
- Owner events endpoint never crashes on DB init/path errors.

## Required checks
- `ruff check <touched files>`
- `python3 -m py_compile <touched files>`
- `.venv/bin/python -m pytest -q <touched tests>`

## Mandatory Delivery Contract
- Include a `Verification Commands` section with copy/paste commands actually run (or to run if blocked):
  - curl commands (when HTTP/API behavior is touched)
  - DB verification commands (sqlite/sql or endpoint reads) when persistence is touched
  - lint/typecheck/test commands with exit status
- Include an `Expected Output Signatures` section for each verification command.
- Include a `Render Env Changes Required` section listing exact variable names/values to set or confirm.
- If unable to execute a verification command, mark `OPERATOR-RUN` and still provide exact command + expected signature.
