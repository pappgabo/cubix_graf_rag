"""J2 exact-year naive retrieval.

The caller passes ``j2_enabled``. This module does not read a question
bank, call a model, or open a database. ``search`` is invoked once.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

FINAL_K = 4
CANDIDATE_K = 12
_YEAR_TOKEN = re.compile(r"(?<!\d)[12]\d{3}(?!\d)")


def distinct_question_years(question: str) -> set[str]:
    """Distinct standalone years in 1000–2999. A repeated year counts once."""
    return {match.group(0) for match in _YEAR_TOKEN.finditer(question or "")}


def _chunk_text(hit) -> str:
    document = hit[0]
    return getattr(document, "page_content", "") or ""


def rerank_exact_year(
    question: str,
    hits: Sequence,
    final_k: int = FINAL_K,
    candidate_k: int = CANDIDATE_K,
) -> list:
    """Stable year order. Hit objects and their scores stay as they arrived.

    Exactly one distinct year: matching chunk texts from the first
    ``candidate_k`` hits, in their original order, then the other hits,
    in their original order, cut to ``final_k``.
    Zero or several years: the original vector prefix of ``final_k``.
    """
    pool = list(hits[:candidate_k])
    years = distinct_question_years(question)
    if len(years) != 1:
        return pool[:final_k]
    year = next(iter(years))
    pattern = re.compile(rf"(?<!\d){re.escape(year)}(?!\d)")
    matched = []
    rest = []
    for hit in pool:
        if pattern.search(_chunk_text(hit)):
            matched.append(hit)
        else:
            rest.append(hit)
    return (matched + rest)[:final_k]


def retrieve_naive_hits(
    question: str,
    search: Callable[[int], Sequence],
    *,
    j2_enabled: bool,
    final_k: int = FINAL_K,
    candidate_k: int = CANDIDATE_K,
) -> list:
    """One ``search(limit)`` call.

    Enabled and exactly one distinct year: ``search(candidate_k)``, then
    exact-year rerank, then ``final_k``. Otherwise ``search(final_k)``
    and the original vector order.
    """
    use_year_pool = j2_enabled and len(distinct_question_years(question)) == 1
    limit = candidate_k if use_year_pool else final_k
    hits = list(search(limit))
    if not use_year_pool:
        return hits[:final_k]
    return rerank_exact_year(question, hits, final_k=final_k, candidate_k=candidate_k)
