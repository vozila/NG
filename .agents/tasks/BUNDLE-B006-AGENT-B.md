# BUNDLE-B006 — Agent B (Orders + Appointments Backend)

## Tasks
- `TASK-0273`: Implement `features/orders_restaurant.py` with strict schema + tenant isolation.
- `TASK-0274`: Implement `features/appointments_barber.py` with strict schema + tenant isolation.
- `TASK-0275`: Add deterministic notification triggers (SMS/email) with idempotent markers for order/appt updates.

## File scope (exclusive)
- `features/orders_restaurant.py`
- `features/appointments_barber.py`
- related tests
- reference packs for touched domains

## Must verify
- API contract tests for happy path + fail-closed validation.
- DB writes tenant-scoped and idempotent.

## Required checks
- `ruff check <touched files>`
- `python3 -m py_compile <touched files>`
- `.venv/bin/python -m pytest -q <touched tests>`

## Mandatory Delivery Contract
- Include `Verification Commands`, `Expected Output Signatures`, `Render Env Changes Required`, and `OPERATOR-RUN` when blocked.
