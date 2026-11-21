"""Import first, for its side effect: puts this package's own directory,
the kept-unchanged week5-b measurement directory, the kept-unchanged
Phase 5 runner's directory, and the project's ``src`` on ``sys.path`` --
same pattern as ``week6_bootstrap.py``, distinct name for the same
``sys.modules`` collision reason (this process also does ``import
measure as week5measure``, which runs week5-b's own ``_bootstrap``)."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]  # .../naive-rag-baseline
WEEK5B_DIR = PROJECT_ROOT / "diagnostics" / "2026-11-11-week5-b"
PHASE5_DIR = PROJECT_ROOT / "diagnostics" / "2026-11-10-phase5-run"
SRC_DIR = PROJECT_ROOT / "src"

for _path in (HERE, WEEK5B_DIR, PHASE5_DIR, SRC_DIR):
    _str = str(_path)
    if _str not in sys.path:
        sys.path.insert(0, _str)
