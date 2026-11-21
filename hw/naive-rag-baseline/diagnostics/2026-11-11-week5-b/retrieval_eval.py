"""Deterministic retrieval evaluation against the approved golden set's
evidence groups.

Pure logic: takes a question and the set of chunk ids *actually used for
generation in that one run* (not a jelölt/candidate pool), and scores
required-group coverage. Does not know where the chunk ids came from --
that is mode-specific (see generation_runner.py) and callers must mark
whether the ids are a genuine retrieval set or a map/reduce proxy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from golden_set import EvidenceGroup, GoldenQuestion

RetrievalStatus = Literal["scored", "untraceable", "not_applicable"]
NOT_APPLICABLE_REASON = "nem alkalmazható: a local followup szándékosan kikapcsolva"


@dataclass(frozen=True)
class GroupResult:
    group_id: str
    criterion: str | None
    role: str | None
    hit: bool
    any_of_chunk_ids: tuple[str, ...]
    matched_chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalResult:
    question_id: str
    status: RetrievalStatus
    is_proxy: bool
    proxy_note: str | None
    groups: tuple[GroupResult, ...] | None
    hit_count: int | None
    group_count: int
    ratio: float | None
    strict_all_hit: bool | None
    untraceable_reason: str | None = None
    not_applicable_reason: str | None = None


def _group_hit(group: EvidenceGroup, actual_chunk_ids: frozenset[str]) -> tuple[bool, tuple[str, ...]]:
    matched = tuple(cid for cid in group.any_of_chunk_ids if cid in actual_chunk_ids)
    return bool(matched), matched


def evaluate_retrieval(
    question: GoldenQuestion,
    actual_chunk_ids: frozenset[str] | None,
    *,
    is_proxy: bool = False,
    proxy_note: str | None = None,
    untraceable_reason: str | None = None,
    not_applicable: bool = False,
) -> RetrievalResult:
    """Score the required evidence groups' coverage.

    ``actual_chunk_ids=None`` (with ``untraceable_reason`` set) means the
    chunk ids actually used could not be recovered for this run -- the
    result is reported as ``"untraceable"``, never scored as zero hits.

    ``is_proxy`` marks a retrieval-like value that is not a direct
    retrieval set (the global mode's map/reduce basis) -- callers must not
    average a proxy value together with a genuine naiv/lokalis coverage
    ratio; this function only records the flag, the report layer enforces
    the separation.
    """
    required_groups = question.required_evidence_groups()
    group_count = len(required_groups)

    if not_applicable:
        return RetrievalResult(
            question_id=question.id, status="not_applicable", is_proxy=is_proxy,
            proxy_note=proxy_note, groups=None, hit_count=None,
            group_count=group_count, ratio=None, strict_all_hit=None,
            untraceable_reason=None, not_applicable_reason=NOT_APPLICABLE_REASON,
        )

    if actual_chunk_ids is None:
        return RetrievalResult(
            question_id=question.id, status="untraceable", is_proxy=is_proxy,
            proxy_note=proxy_note, groups=None, hit_count=None,
            group_count=group_count, ratio=None, strict_all_hit=None,
            untraceable_reason=untraceable_reason or "actual chunk ids not recovered for this run",
        )

    group_results = []
    for group in required_groups:
        hit, matched = _group_hit(group, actual_chunk_ids)
        group_results.append(GroupResult(
            group_id=group.id, criterion=group.criterion, role=group.role,
            hit=hit, any_of_chunk_ids=group.any_of_chunk_ids, matched_chunk_ids=matched,
        ))
    hit_count = sum(1 for g in group_results if g.hit)
    ratio = (hit_count / group_count) if group_count else None
    strict_all = (hit_count == group_count) if group_count else None
    return RetrievalResult(
        question_id=question.id, status="scored", is_proxy=is_proxy, proxy_note=proxy_note,
        groups=tuple(group_results), hit_count=hit_count, group_count=group_count,
        ratio=ratio, strict_all_hit=strict_all,
    )


def result_to_dict(result: RetrievalResult) -> dict:
    return {
        "question_id": result.question_id,
        "status": result.status,
        "is_proxy": result.is_proxy,
        "proxy_note": result.proxy_note,
        "untraceable_reason": result.untraceable_reason,
        "not_applicable_reason": result.not_applicable_reason,
        "hit_count": result.hit_count,
        "group_count": result.group_count,
        "ratio": result.ratio,
        "strict_all_hit": result.strict_all_hit,
        "groups": (
            [
                {
                    "group_id": g.group_id, "criterion": g.criterion, "role": g.role,
                    "hit": g.hit, "any_of_chunk_ids": list(g.any_of_chunk_ids),
                    "matched_chunk_ids": list(g.matched_chunk_ids),
                }
                for g in result.groups
            ] if result.groups is not None else None
        ),
    }
