"""VOZLIA FILE PURPOSE
Purpose: create FastAPI app and mount enabled features.
Hot path: no (startup only).
Feature flags: VOZ_FEATURE_*.
Failure mode: start with core routes even if no features enabled.
"""

from __future__ import annotations

from fastapi import FastAPI

from core.feature_loader import load_features



def create_app() -> FastAPI:
    app = FastAPI()

    @app.get("/")
    async def root() -> dict[str, bool]:
        return {"ok": True}

    load_features(app)
    return app
