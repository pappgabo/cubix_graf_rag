"""Import first, for its side effect: puts this package's own directory,
the kept-unchanged week5-b measurement directory, the kept-unchanged
Phase 5 runner's directory, and the project's ``src`` on ``sys.path``.

Deliberately NOT named ``_bootstrap`` (like week5-b's own bootstrap
module): this process also does ``import measure as week5measure``, which
itself runs week5-b's own ``import _bootstrap``. Two same-named,
different-content modules would collide in ``sys.modules`` -- whichever
loaded first would silently answer for both. A distinct name here means
week5-b's own ``_bootstrap.py`` loads normally (and adds the Phase 5
runner's own directory itself) once this module has put ``WEEK5B_DIR`` on
``sys.path``.

Week5-b's own modules (``state_store``, ``golden_set``, ``retrieval_eval``,
``correctness_judge``, ``faithfulness_judge``, ``report``, ``langfuse_sync``,
``cost_guard``, ``measure``) are reused unchanged from here -- this file
only makes ``import state_store`` etc. resolvable without copying any of
their code.
"""

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
