# BUNDLE-B001 — Agent C Instructions

Read this file before starting.

## Task
- Primary task: `TASK-0403`
- Task spec: `.agents/tasks/TASK-0403.md`

## Scope (exclusive)
- `AGENTS.md`
- `ops/TASKBOARD.md`
- `ops/CHECKPOINT.md`
- `ops/JOURNAL.md`
- `ops/DECISIONS.md`
- `ops/AGENT_BUNDLES.md`
- `.agents/tasks/*` status sync only

## Must do
1. Keep 3-agent bundle assignments/status consistent.
2. Ensure non-overlapping file ownership remains enforced.
3. Ensure each active task records checks run and render-log review references.
4. Update `.agents/tasks/TASK-0403.md` status and evidence notes.

## Must run checks
- Consistency review of task statuses vs AGENTS.md active assignments.
- Verify referenced log files in `ops/JOURNAL.md` exist in `ops/logs/`.

## Must not edit
- `features/*`
- `tests/*`
- runtime scripts.
