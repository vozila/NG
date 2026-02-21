# BUNDLE-B008 — Agent B (Quality Workers + Release Gates)

## Tasks
- `TASK-0293`: Implement/finish regression worker (`/admin/quality/regression/run`) writing `ops/QUALITY_REPORTS/latest_regression.json`.
- `TASK-0294`: Implement/finish security worker (`/admin/quality/security/run`) with tenant/isolation/config posture checks.
- `TASK-0295`: Implement/finish capacity worker (`/admin/quality/capacity/run`) for staging-safe load profiles.

## File scope (exclusive)
- `features/admin_quality.py`
- `scripts/run_regression.py`
- `scripts/run_security.py`
- `scripts/run_capacity.py`
- related tests
- quality report docs/reference packs

## Must verify
- Workers return deterministic JSON and write expected report artifacts.
- Security checks fail closed on missing auth/unsafe config.

## Required checks
- `ruff check <touched files>`
- `python3 -m py_compile <touched files>`
- `.venv/bin/python -m pytest -q <touched tests>`

## Mandatory Delivery Contract
- Include `Verification Commands`, `Expected Output Signatures`, `Render Env Changes Required`, and `OPERATOR-RUN` when blocked.
