"""Import first. Puts this directory, the unchanged week5-b measurement
directory, the Phase 5 runner, and ``src`` on ``sys.path``."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
WEEK5B_DIR = PROJECT_ROOT / "diagnostics" / "2026-11-11-week5-b"
PHASE5_DIR = PROJECT_ROOT / "diagnostics" / "2026-11-10-phase5-run"
SRC_DIR = PROJECT_ROOT / "src"

for _path in (HERE, WEEK5B_DIR, PHASE5_DIR, SRC_DIR):
    _str = str(_path)
    if _str not in sys.path:
        sys.path.insert(0, _str)
