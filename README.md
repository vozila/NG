# Vozlia NG

NG is the next-generation Vozlia modular monolith (single repo) using **one-file feature modules** under `features/`.

## Key invariants (MVP)
- Features live in `features/<name>.py` and **must not import other features**.
- Each feature is behind a kill-switch env var: `VOZ_FEATURE_<NAME>` (default OFF).
- Hot path (Voice Flow A) must remain minimal.

## Auth policy (control-plane)
- `/admin/*` endpoints require `Authorization: Bearer <VOZ_ADMIN_API_KEY>`.
- `/owner/*` endpoints require `Authorization: Bearer <VOZ_OWNER_API_KEY>`.
- Missing key env vars fail closed (unauthorized).

## Post-call extraction approach
- `POST /admin/postcall/extract` is model-first with strict schema validation.
- Primary proposer: OpenAI Responses API with JSON-schema constrained output.
- Deterministic fallback: local heuristic proposer when model path is disabled/fails.
- Accepted output is always Pydantic-validated before event writes.

## Day 0 commands
```bash
python -m compileall .
python -m ruff check .
pytest -q
VOZ_FEATURE_ADMIN_QUALITY=1 VOZ_FEATURE_SAMPLE=1 python scripts/run_regression.py
```

## WebUI (monorepo)
Web admin UI now lives in `apps/vozlia-admin`.

Local run:
```bash
bash scripts/run_webui.sh dev
```

Other modes:
```bash
bash scripts/run_webui.sh lint
bash scripts/run_webui.sh build
```

Required local env for auth:
- `NEXTAUTH_URL=http://localhost:3000`
- `NEXTAUTH_SECRET=<strong-random-secret>`
- `VOZLIA_CONTROL_BASE_URL=http://localhost:10000`
- `VOZLIA_ADMIN_KEY=<admin-key>`
