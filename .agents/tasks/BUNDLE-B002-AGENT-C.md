# BUNDLE-B002 — Agent C (Portal/UI)

## Tasks
- `TASK-0236`: Business profile editor UI.
- `TASK-0237`: Template selection UI + preview.
- `TASK-0238`: OCR upload + review UI.

## Task specs
- `.agents/tasks/TASK-0236.md`
- `.agents/tasks/TASK-0237.md`
- `.agents/tasks/TASK-0238.md`

## File scope (exclusive)
- Portal/front-end repo files only.
- Default portal repo path: `../vozlia-admin`
- Do not edit NG backend files for this task.
- No backend/voice/ops files in NG backend repo.

## Must verify
- Provide UI smoke steps and API contract assumptions.
- If agent cannot run UI locally, provide operator steps and screenshots checklist.

## Required checks
- Front-end lint/build/test commands for the UI repo.

## Mandatory Delivery Contract
- Include a `Verification Commands` section with copy/paste commands actually run (or to run if blocked):
  - curl commands (when HTTP/API behavior is touched)
  - DB verification commands (sqlite/sql or endpoint reads) when persistence is touched
  - lint/typecheck/test commands with exit status
- Include an `Expected Output Signatures` section for each verification command.
- Include a `Render Env Changes Required` section listing exact variable names/values to set or confirm.
- If unable to execute a verification command, mark `OPERATOR-RUN` and still provide exact command + expected signature.
