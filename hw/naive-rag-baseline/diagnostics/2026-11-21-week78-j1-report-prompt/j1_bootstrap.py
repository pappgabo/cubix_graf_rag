"""Import first, for its side effect: puts this package's own directory,
the kept-unchanged Phase 3 report-generation directory, the kept-unchanged
week5-b measurement directory (for its ``cost_guard.SharedCostLedger``,
reused unmodified), and the project's ``src`` on ``sys.path`` -- so
``import generate_reports_v3`` (for its reusable, pure
``validate_report``/``resolve_statements``/``extract_system_prompt``
helpers, unmodified) and ``import cost_guard`` resolve without copying
their code."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]  # .../naive-rag-baseline
PHASE3_DIR = PROJECT_ROOT / "diagnostics" / "2026-11-10-phase3-measurement"
WEEK5B_DIR = PROJECT_ROOT / "diagnostics" / "2026-11-11-week5-b"
SRC_DIR = PROJECT_ROOT / "src"

for _path in (HERE, PHASE3_DIR, WEEK5B_DIR, SRC_DIR):
    _str = str(_path)
    if _str not in sys.path:
        sys.path.insert(0, _str)
