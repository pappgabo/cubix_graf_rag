"""Entry point that works even when the project path has non-ASCII
characters (e.g. a Windows path containing "1_hét").

`uv run naive-rag ...` normally works via an editable install: uv writes the
absolute path to `src/` into a `.pth` file in `.venv/Lib/site-packages/`.
CPython's `site` module always decodes the *contents* of `.pth` files with
`encoding="locale"` (see cpython `Lib/site.py`, `addpackage()`) -- and that
specific codec deliberately ignores `PYTHONUTF8`/UTF-8 mode by design. On a
Windows machine whose system (non-Unicode) codepage is not UTF-8, a non-ASCII
character in the path (like "é") gets mis-decoded, the resulting path does
not exist, and `src/` is silently never added to `sys.path`:

    ModuleNotFoundError: No module named 'naive_rag'

This script sidesteps that entirely by adding `src/` to `sys.path` itself,
using `pathlib`/`__file__` (Unicode-safe on Windows, unlike `.pth` parsing).

Usage (equivalent to `uv run naive-rag ...`):
    uv run python run.py ingest
    uv run python run.py ask "..."
    uv run python run.py baseline
    uv run python run.py serve
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from naive_rag.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
