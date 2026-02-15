# Vozlia NG

NG is the next-generation Vozlia modular monolith (single repo) using **one-file feature modules** under `features/`.

## Key invariants (MVP)
- Features live in `features/<name>.py` and **must not import other features**.
- Each feature is behind a kill-switch env var: `VOZ_FEATURE_<NAME>` (default OFF).
- Hot path (Voice Flow A) must remain minimal.

## Day 0 commands
```bash
python -m compileall .
python -m ruff check .
ptest -q
VOZ_FEATURE_ADMIN_QUALITY=1 VOZ_FEATURE_SAMPLE=1 python scripts/run_regression.py
```
