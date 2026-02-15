"""VOZLIA FILE PURPOSE
Purpose: FastAPI entrypoint for NG.
Hot path: no (process-level startup only).
Feature flags: none.
Failure mode: fail fast on import errors.
"""

from core.app import create_app

app = create_app()
