# BUNDLE-B006 — Agent C (Portal Order/Appointment Ops UI)

## Tasks
- `TASK-0276`: Add owner portal view for order requests (status + timestamps + caller).
- `TASK-0277`: Add owner portal view for appointment requests (requested slot + status).
- `TASK-0278`: Add operator controls to mark confirmed/cancelled with deterministic audit notes.

## File scope (exclusive)
- Portal/front-end repo files only (`apps/vozlia-admin`)

## Must verify
- UI actions map to backend owner/inbox/order/appointment endpoints.
- Status transitions reflected without page reload where possible.

## Required checks
- Front-end lint/build/test commands for the UI repo.

## Mandatory Delivery Contract
- Include `Verification Commands`, `Expected Output Signatures`, `Render Env Changes Required`, and `OPERATOR-RUN` when blocked.
