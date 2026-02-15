"""VOZLIA FILE PURPOSE
Purpose: discover and mount one-file feature modules from `features/`.
Hot path: no (startup only).
Feature flags: VOZ_FEATURE_*.
Failure mode: invalid feature => skipped (debug logs only when VOZLIA_DEBUG=1).
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from typing import Any

from fastapi import FastAPI

from core.config import env_flag, is_debug
from core.logging import logger
from core.registry import FeatureSpec, set_discovered, set_enabled

_ENV_RE = re.compile(r"^VOZ_FEATURE_[A-Z0-9_]+$")


def _validate(feature: Any) -> dict[str, Any] | None:
    if not isinstance(feature, dict):
        return None
    required = {"key", "router", "enabled_env", "selftests", "security_checks", "load_profile"}
    if not required.issubset(feature.keys()):
        return None
    if not isinstance(feature.get("key"), str) or not feature["key"]:
        return None
    env = feature.get("enabled_env")
    if not isinstance(env, str) or not _ENV_RE.match(env):
        return None
    return feature


def load_features(app: FastAPI) -> None:
    import features  # package

    discovered: dict[str, FeatureSpec] = {}
    enabled: dict[str, FeatureSpec] = {}

    for mod in pkgutil.iter_modules(features.__path__):
        if mod.ispkg or mod.name.startswith("_") or mod.name == "__init__":
            continue
        m = importlib.import_module(f"features.{mod.name}")
        d = _validate(getattr(m, "FEATURE", None))
        if d is None:
            if is_debug():
                logger.warning("FEATURE_INVALID module=%s", mod.name)
            continue

        spec = FeatureSpec(
            key=d["key"],
            enabled_env=d["enabled_env"],
            router=d["router"],
            selftests=d["selftests"],
            security_checks=d["security_checks"],
            load_profile=d["load_profile"],
         )
        discovered[spec.key] = spec

        if env_flag(spec.enabled_env, "0"):
            app.include_router(spec.router)
            enabled[spec.key] = spec

    set_discovered(discovered)
    set_enabled(enabled)

    if is_debug():
        logger.info("FEATURES_DISCOVERED keys=%s", sorted(discovered.keys()))
        logger.info("FEATURES_ENABLED keys=%s", sorted(enabled.keys()))
