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

## Mandatory Delivery Contract
- Include a `Verification Commands` section with copy/paste commands actually run (or to run if blocked):
  - curl commands (when HTTP/API behavior is touched)
  - DB verification commands (sqlite/sql or endpoint reads) when persistence is touched
  - lint/typecheck/test commands with exit status
- Include an `Expected Output Signatures` section for each verification command.
- Include a `Render Env Changes Required` section listing exact variable names/values to set or confirm.
- If unable to execute a verification command, mark `OPERATOR-RUN` and still provide exact command + expected signature.
