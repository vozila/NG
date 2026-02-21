# BUNDLE-B008 — Agent C (Portal QA + Operator Runbooks)

## Tasks
- `TASK-0296`: Add portal release-check page that surfaces backend quality report status.
- `TASK-0297`: Add operator runbook page with copyable bundle verification commands (curl + env checklist).
- `TASK-0298`: Add tenant launch checklist UI for production handoff.

## File scope (exclusive)
- Portal/front-end repo files only (`apps/vozlia-admin`)

## Must verify
- Portal can render quality status from backend without exposing secrets.
- Operator commands are copy/paste accurate and versioned per bundle.

## Required checks
- Front-end lint/build/test commands for the UI repo.
- For any curl verification, first run: `source scripts/load_operator_env.sh`

## Mandatory Delivery Contract
- Include `Verification Commands`, `Expected Output Signatures`, `Render Env Changes Required`, and `OPERATOR-RUN` when blocked.
