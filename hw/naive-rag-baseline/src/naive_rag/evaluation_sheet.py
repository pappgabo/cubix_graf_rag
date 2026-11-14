"""Offline evaluation-sheet template: one row per (question, mode).

This module only builds the STRUCTURE. It never fills in a real
correctness or support judgement -- every row's ``status`` is
``"előzetes"`` (preliminary) until a human (the user) completes it. No
code in this repository should ever mark a row as final.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CORRECTNESS_VALUES = ("helyes", "hiányos", "téves", "elutasított")
SUPPORT_VALUES = (
    "forrásrészletben alátámasztott",
    "csak a gráfban alátámasztott",
    "egyikben sem",
    "nem eldönthető a rendelkezésre álló bizonyítékból",
)
ERROR_CATEGORY_VALUES = ("keresési hiba", "generálási hiba", "nem eldönthető")
MODES = ("naiv", "lokalis", "globalis")


@dataclass
class EvaluationRow:
    question_id: str
    mode: str
    answer: str | None = None
    context_size_tokens: int | str | None = None
    context_size_is_estimate: bool = True
    call_count: int | None = None
    cost_usd: float | str | None = None
    correctness: str | None = None  # one of CORRECTNESS_VALUES, or None
    support: str | None = None  # one of SUPPORT_VALUES, or None
    error_category: str | None = None  # one of ERROR_CATEGORY_VALUES, or None
    justification: str = ""
    evidence_reference: str = ""
    status: str = "előzetes"

    def to_json(self) -> dict:
        return asdict(self)


def build_template(question_ids: list[str], modes: tuple[str, ...] = MODES) -> list[EvaluationRow]:
    return [EvaluationRow(question_id=qid, mode=mode) for qid in question_ids for mode in modes]


def save_template(path: Path, rows: list[EvaluationRow]) -> None:
    path.write_text(
        json.dumps([row.to_json() for row in rows], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


def summarize_by_type(rows: list[EvaluationRow], labels_by_question: dict[str, str]) -> dict:
    """Preliminary per-type counts of filled-in correctness values. Returns
    an all-zero/empty skeleton when nothing has been filled in yet -- this
    is itself not a final result."""
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        label = labels_by_question.get(row.question_id, "unknown")
        bucket = summary.setdefault(label, {value: 0 for value in CORRECTNESS_VALUES})
        if row.correctness in CORRECTNESS_VALUES:
            bucket[row.correctness] += 1
    return summary
