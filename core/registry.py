"""VOZLIA FILE PURPOSE
Purpose: feature registry (enabled features and metadata).
Hot path: low (read-only lookups).
Feature flags: VOZ_FEATURE_*.
Failure mode: registry empty => app has only core routes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass=True, frozen=True)
class FeatureSpec:
    key: str
    enabled_env: str
    router: Any
    selftests: Callable[[], Any]
    security_checks: Callable[[], Any]
    load_profile: Callable[[], Any]


_DISCOVERED: dict[str, FeatureSpec] = {}
_ENABLED: dict[str, FeatureSpec] = {}


def set_discovered(specs: dict[str, FeatureSpec]) -> None:
    global _DISCOVERED
    _DISCOVERED = dict(specs)


def set_enabled(specs: dict[str, FeatureSpec]) -> None:
    global _ENABLED
    _ENABLED = dict(specs)


def discovered_features() -> dict[str, FeatureSpec]:
    return dict(_DISCOVERED)


def enabled_features() -> dict[str, FeatureSpec]:
    return dict(_ENABLED)
