"""Evaluation-side comparison between the router's chosen mode and a
question's type label. This mapping is NEVER given to the router (see
search_router.py) -- it exists only so the evaluation code can report
where the router's choice disagrees with the "feladattípus szerinti
megfeleltetés" (task-type mapping), a convention fixed in advance, not a
claim that the mapped mode always gives the best answer.

The router was developed with knowledge of this exact question set
(Q01-Q13), so a match or mismatch against this mapping is NOT an
independent test of the router -- see the Phase 5 report.
"""

from __future__ import annotations

from dataclasses import dataclass

TASK_TYPE_TO_MODE = {
    "simple": "naiv",
    "multi-hop": "lokalis",
    "global": "globalis",
}


@dataclass(frozen=True)
class RouterComparison:
    question_id: str
    label: str
    expected_mode: str
    chosen_mode: str | None
    matches_mapping: bool | None  # None when chosen_mode is unknown (error/invalid)


def compare_to_mapping(question_id: str, label: str, chosen_mode: str | None) -> RouterComparison:
    expected = TASK_TYPE_TO_MODE.get(label)
    if expected is None:
        raise ValueError(f"no task-type mapping for label {label!r}")
    matches = None if chosen_mode is None else chosen_mode == expected
    return RouterComparison(
        question_id=question_id, label=label, expected_mode=expected,
        chosen_mode=chosen_mode, matches_mapping=matches,
    )


def mismatches(comparisons: list[RouterComparison]) -> list[RouterComparison]:
    """Only the evaluation code builds this list -- never the router."""
    return [c for c in comparisons if c.matches_mapping is False]
