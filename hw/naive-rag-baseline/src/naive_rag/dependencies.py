"""External (non-pip) dependencies: discovery and fail-fast checks.

This module only *finds* binaries and reports what is missing. Telling the user
how to install something is platform specific and lives in the CLI layer.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterable
from functools import cache
from pathlib import Path


class MissingDependency(RuntimeError):
    """A required external program is not installed / not on PATH."""

    def __init__(self, name: str, needed_for: str) -> None:
        self.name = name
        self.needed_for = needed_for
        super().__init__(f"'{name}' was not found (needed for {needed_for}).")


@cache
def find_pandoc() -> str | None:
    """Path to the pandoc executable, or None if it cannot be found."""
    exe = shutil.which("pandoc")
    if exe:
        return exe
    # winget installs pandoc per user and only updates PATH for *new*
    # terminals, so a still-open terminal would miss it.
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            cand = Path(local) / "Pandoc" / "pandoc.exe"
            if cand.exists():
                return str(cand)
    return None


def require_pandoc() -> str:
    """Path to pandoc; raises MissingDependency if it is not available."""
    exe = find_pandoc()
    if exe is None:
        raise MissingDependency("pandoc", "DOCX documents")
    return exe


# Document format -> check for the external program its loader needs.
_REQUIRED_BY_FORMAT = {"docx": require_pandoc}


def require_for_formats(formats: Iterable[str]) -> None:
    """Fail fast: raise if a format in `formats` needs a missing program."""
    for fmt in sorted(set(formats)):
        check = _REQUIRED_BY_FORMAT.get(fmt)
        if check:
            check()
