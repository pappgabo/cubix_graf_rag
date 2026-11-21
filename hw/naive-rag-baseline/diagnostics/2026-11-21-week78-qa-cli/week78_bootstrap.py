"""Import first, for its side effect: puts this package's own directory,
the kept-unchanged week5-b measurement directory, the kept-unchanged
Phase 5 runner's directory, the kept-unchanged week6 drift directory, and
the project's ``src`` on ``sys.path``.

Deliberately NOT named ``_bootstrap`` or ``week6_bootstrap`` (collision
reasons identical to ``week6_bootstrap.py``'s own docstring: this process
also does ``import week6_bootstrap``, which itself does ``import
measure as week5measure`` via ``drift_measure``/``drift_runner``, and that
chain already inserts WEEK5B_DIR/PHASE5_DIR/SRC_DIR -- a same-named
bootstrap module here would collide in ``sys.modules``).

No module under ``src/naive_rag`` or under any existing ``diagnostics/*``
directory is copied or modified by this file -- it only extends
``sys.path`` so ``import generation_runner``, ``import drift_runner``,
``import cost_guard``, ``import run_phase5`` etc. resolve without copying
their code.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]  # .../naive-rag-baseline
WEEK5B_DIR = PROJECT_ROOT / "diagnostics" / "2026-11-11-week5-b"
PHASE5_DIR = PROJECT_ROOT / "diagnostics" / "2026-11-10-phase5-run"
WEEK6_DRIFT_DIR = PROJECT_ROOT / "diagnostics" / "2026-11-14-week6-drift"
SRC_DIR = PROJECT_ROOT / "src"

for _path in (HERE, WEEK5B_DIR, PHASE5_DIR, WEEK6_DRIFT_DIR, SRC_DIR):
    _str = str(_path)
    if _str not in sys.path:
        sys.path.insert(0, _str)
