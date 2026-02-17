# CODE_DRIFT_CONTROL — Vozlia NG

This file is canonical process for controlling code drift in NG.

## 1) Touched File Contract
- Every change must list **explicit files touched** in its ticket.
- No drive-by refactors. If it isn't required for the ticket, don't change it.
- Every new/modified Python module must start with a **FILE PURPOSE** header describing:
  - purpose
  - hot-path impact (yes/no)
  - feature flags involved
  - failure mode

## 2) Modular Monolith + One-File Features
- Features are single-file plugins: `features/<feature_key>.py`.
- **No cross-feature imports**. Features may only import:
  - stdlib
  - `core/*` (including `core/ports.py`)
- Each feature has a kill switch env var: `VOZ_FEATURE_<NAME>` (default OFF).
- Rollback is always possible by flipping the kill switch to `0`.

## 3) Voice Hot Path Discipline (Flow A)
- Flow A is sacred: Twilio → <FAstAPI WS `/twilio/stream` �� OpenAI Realtime → Twilio
- Flow A must not do heavy planning or unbounded work.
- Skill creation / OPR / crawling happens out-of-band.

## 4) Logging and Debug Discipline
- Diagnostic logs must be gated behind `VOZLIA_DEBUG=1 ` (default OFF).
- When enabled, log breadcrumbs: request received → routing decision → tool calls → response.

## 5) No Patch Without Proof
Before approving/merging any PR:
1) `python -m compileall .`
2) smoke-import all modified modules
3) `python -m ruff check .`
4) `pytest -q`
5) `POST /admin/quality/regression/run` (or `scripts/run_regression.py`)

If any fail: STOP. Do not merge.

## 6) Evidence Rule
For every merge, capture ≤5 log lines or outputs proving:
- feature loader mounted expected features (when enabled)
- regression runner executed and wrote report

## 7) Touched Registry (append-only)
## 2026-02-17 — Shared Line Access Routing
- `features/shared_line_access.py` (new): Twilio entry + gather callback routing by dedicated/shared line, stream parameter injection, deterministic selftests.
- `features/voice_flow_a.py`: parse and retain `tenant_id`, `tenant_mode`, `rid` from Twilio start custom parameters (debug-gated breadcrumbs).
- `tests/test_voice_flow_a.py`: parser expectations updated for `tenant_mode` and `rid`.
- `ops/JOURNAL.md`: journaled feature rollout details, flags, endpoints, rollback.
