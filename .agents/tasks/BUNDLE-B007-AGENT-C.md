# BUNDLE-B007 — Agent C (Portal Skill Studio)

## Tasks
- `TASK-0286`: Add owner portal analytics Q&A panel with query history and evidence links.
- `TASK-0287`: Add skill registry UI (draft/approved/disabled) with tenant scoping.
- `TASK-0288`: Add schedule controls for approved skills (manual run + next-run preview).

## File scope (exclusive)
- Portal/front-end repo files only (`apps/vozlia-admin`)

## Must verify
- UI displays trace/evidence IDs from backend responses.
- Skill state transitions are deterministic and reversible.

## Required checks
- Front-end lint/build/test commands for the UI repo.
- For any curl verification, first run: `source scripts/load_operator_env.sh`

## Mandatory Delivery Contract
- Include `Verification Commands`, `Expected Output Signatures`, `Render Env Changes Required`, and `OPERATOR-RUN` when blocked.
