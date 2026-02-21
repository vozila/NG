# BUNDLE-B005 — Agent C (Portal Auth + Tenant Guardrails)

## Tasks
- `TASK-0266`: Add explicit admin preflight panel for required env/auth health checks (session, API base URL, backend reachability).
- `TASK-0267`: Add tenant-context lock in admin UI to avoid accidental cross-tenant operations.
- `TASK-0268`: Add operator-facing diagnostics section with copyable curl commands for owner event/inbox verification.

## File scope (exclusive)
- Portal/front-end repo files only (`apps/vozlia-admin`)

## Must verify
- `/admin` shows deterministic configuration errors when auth/env is missing.
- Tenant context is visible and required before mutating actions.
- Run topology/auth preflight first:
  - verify collapsed NG runtime vs split control-plane
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
