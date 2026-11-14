"""Import first, for its side effect: puts this package's own directory,
the kept-unchanged Phase 5 runner's directory, and the project's ``src``
on ``sys.path``. ``run_phase5.py`` itself then inserts ``src`` again when
imported (harmless, same path); this just makes ``import run_phase5``
resolvable from here without copying any of its code.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]  # .../naive-rag-baseline
PHASE5_DIR = PROJECT_ROOT / "diagnostics" / "2026-11-10-phase5-run"
SRC_DIR = PROJECT_ROOT / "src"

for _path in (HERE, PHASE5_DIR, SRC_DIR):
    _str = str(_path)
    if _str not in sys.path:
        sys.path.insert(0, _str)
