"""VOZLIA FILE PURPOSE
Purpose: policy checks for feature modules (FEATURE contract + no cross-feature imports).
Hot path: no.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

RE_ENV = re.compile(r"VOZ_FEATURE_[A-Z0-9_]+")

REQUIRED = {"key", "router", "enabled_env", "selftests", "security_checks", "load_profile"}


def fail(msg: str) -> None:
    print(f"FEATURE_CHECK_FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    feat_dir = Path("features")
    for path in sorted(feat_dir.glob("*.py")):
        if path.name.startswith("_") or path.name == "__init__.py":
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "features" or a.name.startswith("features."):
                        fail(f"cross-feature import in {path}")
            if isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    fail(f"relative import not allowed in {path}")
                mod = node.module or ""
                if mod == "features" or mod.startswith("features."):
                    fail(f"cross-feature import in {path}")

        # FEATURE dict (best-effort)
        if "FEATURE" not in src:
            fail(f"FEATURE missing in {path}")
        for k in REQUIRED:
            if f"''{k}''" not in src and f'\"{k}\"' not in src:
                fail(f"FEATURE missing key {k} in {path}")
        if not RE_ENV.search(src):
            fail(f"enabled_env missing/invalid in {path}")

    print("FEATURE_CHECK_OK")


if __name__ == "__main__":
    main()
