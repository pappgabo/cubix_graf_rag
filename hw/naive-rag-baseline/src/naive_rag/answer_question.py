"""Thin "question -> router -> search" entry point.

No existing module ties the router's decision to an actual search call:
`generation_runner`'s measurement helpers and `run_phase5.run_router_all`
only measure the router's JSON decision, they never dispatch on it (see
docs/week6-atadas.md, point 3). This module is the minimal missing glue.
It does not change the router or any of the four search implementations
-- it only calls whichever one the router (or the caller, explicitly)
picked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import search_router


def answer_question(
    question_id: str,
    question_text: str,
    *,
    mode_fns: dict[str, Callable[[str], object]],
    raw_caller: search_router.RawCaller | None = None,
    mode: str | None = None,
    log_path: Path | None = None,
) -> dict:
    """Dispatch to `mode_fns[mode]`.

    An explicit `mode` bypasses the router entirely (direct mode
    selection). Otherwise `search_router.route_one` decides, and its
    returned mode is what actually gets called -- the router's decision
    is never discarded or merely recorded. `mode_fns` may hold any subset
    of the four modes; the three pre-existing ones are untouched by this
    module.
    """
    if mode is not None:
        if mode not in mode_fns:
            raise ValueError(f"no search function registered for mode {mode!r}")
        return {
            "question_id": question_id, "mode": mode, "mode_source": "explicit",
            "result": mode_fns[mode](question_text),
        }

    if raw_caller is None:
        raise ValueError("raw_caller is required for automatic routing")
    route_record = search_router.route_one(
        question_id, question_text, raw_caller, log_path=log_path)
    chosen_mode = route_record.get("mode")
    if chosen_mode not in mode_fns:
        return {
            "question_id": question_id, "mode": chosen_mode, "mode_source": "router",
            "route_record": route_record, "result": None,
            "error": "router did not return a mode with a registered search function",
        }
    return {
        "question_id": question_id, "mode": chosen_mode, "mode_source": "router",
        "route_record": route_record, "result": mode_fns[chosen_mode](question_text),
    }
