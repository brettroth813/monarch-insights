#!/usr/bin/env python3
"""Sync the top-level ``monarch_insights/`` package into the HACS integration's vendored
directory so HACS ships a self-contained copy.

Canonical copy lives at ``monarch_insights/`` (used by tests, CLI, demo). HACS ships
``custom_components/monarch_insights/`` only — the integration's ``__init__.py`` inserts
``_vendored/`` onto ``sys.path`` so ``from monarch_insights...`` imports resolve.

Run this before every commit that touches the library:

    python scripts/sync_vendored.py

The script is intentionally small — it rsyncs using ``shutil`` and prunes ``__pycache__``
so the tree stays reproducible.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "monarch_insights"
DST = REPO / "custom_components" / "monarch_insights" / "_vendored" / "monarch_insights"

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store")


def main() -> int:
    if not SRC.is_dir():
        print(f"source missing: {SRC}", file=sys.stderr)
        return 1
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST, ignore=IGNORE)
    # Count files for sanity output.
    count = sum(1 for _ in DST.rglob("*.py"))
    print(f"synced {count} .py files → {DST.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
