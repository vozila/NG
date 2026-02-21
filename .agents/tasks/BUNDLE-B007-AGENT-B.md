# BUNDLE-B007 — Agent B (Dynamic Skill Engine)

## Tasks
- `TASK-0283`: Implement deterministic owner analytics engine (`features/analytics_owner_qa.py`) with strict QuerySpec validation.
- `TASK-0284`: Implement dynamic DB skill persistence/reuse (`features/dynamic_db_skill.py`) with approval workflow.
- `TASK-0285`: Add pluggable skill adapters for web/API lookup skeletons (`features/dynamic_websearch_skill.py`, `features/dynamic_api_skill.py`) behind flags and allowlists.

## File scope (exclusive)
- `features/analytics_owner_qa.py`
- `features/dynamic_db_skill.py`
- `features/dynamic_websearch_skill.py`
- `features/dynamic_api_skill.py`
- related tests
- reference packs for touched domains

## Must verify
- All LLM-generated action specs validated before execution.
- SQL allowlist/read-only protections enforced.

## Required checks
- `ruff check <touched files>`
- `python3 -m py_compile <touched files>`
- `.venv/bin/python -m pytest -q <touched tests>`

## Mandatory Delivery Contract
- Include `Verification Commands`, `Expected Output Signatures`, `Render Env Changes Required`, and `OPERATOR-RUN` when blocked.
