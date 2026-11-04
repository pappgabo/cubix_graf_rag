"""Document ids named by the week-1 question file.

A backtick token is a concrete doc id when it matches the corpus id
pattern. A wildcard such as ``driver-*`` is not expanded and is not a
member of the processing round.
"""

from __future__ import annotations

import re

_QUESTION = re.compile(r"^### (Q\d+)\b")
_DOC_ID = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`")


def documents_by_question(text: str) -> dict[str, tuple[str, ...]]:
    """Map ``Q01`` to the concrete doc ids on its Dokumentum line."""
    current: str | None = None
    found: dict[str, tuple[str, ...]] = {}
    for line in text.splitlines():
        heading = _QUESTION.match(line)
        if heading:
            current = heading.group(1)
            continue
        if current and line.startswith("**Dokumentum"):
            found[current] = tuple(dict.fromkeys(_DOC_ID.findall(line)))
            current = None
    return found


def question_ids_from_scope(spec: str) -> tuple[str, ...]:
    """``Q01`` or an inclusive range ``Q01-Q08``."""
    if "-" not in spec:
        return (spec,)
    start, end = spec.split("-", 1)
    if not (start.startswith("Q") and end.startswith("Q")):
        raise ValueError(f"Question scope is not Qnn-Qnn: {spec}")
    first = int(start[1:])
    last = int(end[1:])
    if first > last:
        raise ValueError(f"Question scope is reversed: {spec}")
    return tuple(f"Q{number:02d}" for number in range(first, last + 1))


def doc_ids_for(text: str, question_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Concrete doc ids for the questions, in first-seen order."""
    by_question = documents_by_question(text)
    ordered: list[str] = []
    for question_id in question_ids:
        for doc_id in by_question.get(question_id, ()):
            if doc_id not in ordered:
                ordered.append(doc_id)
    return tuple(ordered)
