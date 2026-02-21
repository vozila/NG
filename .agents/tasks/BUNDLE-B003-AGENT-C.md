# BUNDLE-B003 — Agent C (Portal/UI)

## Tasks
- `TASK-0246`: Inbox actions UI.
- `TASK-0247`: Notification settings UI.
- `TASK-0248`: Appointment request view.

## File scope (exclusive)
- Portal/front-end repo files only.

## Must verify
- Provide UI smoke test steps for lead qualification and handled state.
- If direct execution unavailable, provide operator script and expected UI outcomes.
- Run topology/auth preflight first:
  - verify collapsed NG runtime vs split control-plane
  - do not assume `/admin/settings` exists on NG runtime
  - use Bearer auth checks for NG `/owner/*` and `/admin/*` probes

## Required checks
- Front-end lint/build/test commands for the UI repo.
- For any curl verification, first run: `source scripts/load_operator_env.sh`

## Mandatory Delivery Contract
- Include a `Verification Commands` section with copy/paste commands actually run (or to run if blocked):
  - curl commands (when HTTP/API behavior is touched)
  - DB verification commands (sqlite/sql or endpoint reads) when persistence is touched
  - lint/typecheck/test commands with exit status
- Include an `Expected Output Signatures` section for each verification command.
- Include a `Render Env Changes Required` section listing exact variable names/values to set or confirm.
- If unable to execute a verification command, mark `OPERATOR-RUN` and still provide exact command + expected signature.
