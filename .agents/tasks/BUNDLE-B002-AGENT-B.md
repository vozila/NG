# BUNDLE-B002 — Agent B (Backend/Templates/OCR)

## Tasks
- `TASK-0233`: Business Profile API (owner CRUD).
- `TASK-0234`: Business templates v1.
- `TASK-0235`: OCR ingest (schema-first, pending review flow).

## File scope (exclusive)
- `features/business_profile.py`
- `features/business_templates.py`
- `features/ocr_ingest.py`
- `tests/test_business_profile*.py`
- `tests/test_business_templates*.py`
- `tests/test_ocr_ingest*.py`
- Ops writeback:
  - `ops/REFERENCE_PACKS/business_profile.md`
  - `ops/REFERENCE_PACKS/business_templates.md`
  - `ops/REFERENCE_PACKS/ocr_ingest.md`

## Must verify
- Execute API curls from bundle proof gate where endpoints exist.
- If not possible locally, provide exact commands and expected response structure.

## Required checks
- `ruff check features/business_profile.py features/business_templates.py features/ocr_ingest.py`
- `python3 -m py_compile features/business_profile.py features/business_templates.py features/ocr_ingest.py`
- targeted pytest for added modules.

## Mandatory Delivery Contract
- Include a `Verification Commands` section with copy/paste commands actually run (or to run if blocked):
  - curl commands (when HTTP/API behavior is touched)
  - DB verification commands (sqlite/sql or endpoint reads) when persistence is touched
  - lint/typecheck/test commands with exit status
- Include an `Expected Output Signatures` section for each verification command.
- Include a `Render Env Changes Required` section listing exact variable names/values to set or confirm.
- If unable to execute a verification command, mark `OPERATOR-RUN` and still provide exact command + expected signature.
