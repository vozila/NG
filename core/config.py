"""VOZLIA FILE PURPOSE
Purpose: environment configuration helpers (safe defaults).
Hot path: yes (read-only env lookups; lightweight).
Feature flags: VOZLIA_DEBUG, VOZ_FEATURE_*.
Failure mode: safe defaults when unset.
"""

from __future__ import annotations

import os


def env_flag(name: str, default: str = "0") -> bool:
    v = (os.getenv(name) or default).strip().lower()
    return v in ("1", "true", "yes", "on")


def is_debug() -> bool:
    return env_flag("VOZLIA_DEBUG", "0")
