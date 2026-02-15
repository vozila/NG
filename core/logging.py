"""VOZLIA FILE PURPOSE
Purpose: logging setup with strict debug gating.
Hot path: yes (logger calls occur in hot paths; default is quiet).
Feature flags: VOZLIA_DEBUG.
Failure mode: never crash due to logging.
"""

from __future__ import annotations

import logging

from core.config import is_debug


def _configure() -> logging.Logger:
    logger = logging.getLogger("vozlia_ng")
    if logger.handlers:
        return logger

    handler = logging.StreamHandler()
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO if is_debug() else logging.WARNING)
    return logger


logger = _configure()
