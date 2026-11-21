"""Offline mocks for the J2 exact-year naive retrieval. No model or database."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from naive_rag.naive_year_rerank import (
    CANDIDATE_K,
    FINAL_K,
    distinct_question_years,
    retrieve_naive_hits,
)


def _hit(text: str, score: float, chunk_id: str, meta_year: str | None = None):
    metadata = {"chunk_id": chunk_id}
    if meta_year is not None:
        metadata["year"] = meta_year
    return SimpleNamespace(page_content=text, metadata=metadata), score


def _ids(hits) -> list[str]:
    return [hit[0].metadata["chunk_id"] for hit in hits]


class _Search:
    def __init__(self, hits):
        self.hits = hits
        self.limits = []

    def __call__(self, limit: int):
        self.limits.append(limit)
        return self.hits[:limit]


class YearExtractionTests(unittest.TestCase):
    def test_standalone_bounds_and_repeats(self):
        self.assertEqual(distinct_question_years(""), set())
        self.assertEqual(distinct_question_years("no year"), set())
        self.assertEqual(distinct_question_years("in 999 and 3000"), set())
        self.assertEqual(distinct_question_years("from 1000 to 2999"), {"1000", "2999"})
        self.assertEqual(distinct_question_years("2016 and again 2016"), {"2016"})
        self.assertEqual(distinct_question_years("code 12016 and 20160"), set())
        self.assertEqual(distinct_question_years("2014-15 and 2016"), {"2014", "2016"})


class RetrieveTests(unittest.TestCase):
    def _pool(self):
        hits = [_hit(f"season {2020 + i}", 1 - i / 100, f"c{i}") for i in range(13)]
        hits[1] = _hit("also 2016 later", 0.9, "m2")
        hits[5] = _hit("the 2016 season", 0.5, "m1")
        hits[12] = _hit("2016 beyond the pool", 0.01, "outside")
        return hits

    def test_enabled_one_year_searches_once_and_keeps_stable_order_and_scores(self):
        pool = self._pool()
        search = _Search(pool)
        chosen = retrieve_naive_hits("the 2016 race", search, j2_enabled=True)
        self.assertEqual(search.limits, [CANDIDATE_K])
        self.assertEqual(_ids(chosen), ["m2", "m1", "c0", "c2"])
        self.assertEqual([hit[1] for hit in chosen], [0.9, 0.5, 1.0, 0.98])
        self.assertIs(chosen[0], pool[1])
        self.assertEqual(len(chosen), FINAL_K)

    def test_zero_or_several_years_stay_on_one_top_4_search(self):
        pool = self._pool()
        for question in ("who won?", "2016 versus 2021", "2016 2016 2021"):
            search = _Search(pool)
            chosen = retrieve_naive_hits(question, search, j2_enabled=True)
            self.assertEqual(search.limits, [FINAL_K])
            self.assertEqual(_ids(chosen), ["c0", "m2", "c2", "c3"])

    def test_disabled_switch_keeps_the_original_top_4(self):
        pool = self._pool()
        search = _Search(pool)
        chosen = retrieve_naive_hits("the 2016 race", search, j2_enabled=False)
        self.assertEqual(search.limits, [FINAL_K])
        self.assertEqual(_ids(chosen), ["c0", "m2", "c2", "c3"])

    def test_year_only_in_metadata_does_not_match(self):
        hits = [
            _hit("no year in the text", 0.9, "a", meta_year="2016"),
            _hit("written 2016", 0.2, "b"),
        ]
        search = _Search(hits)
        chosen = retrieve_naive_hits("about 2016", search, j2_enabled=True)
        self.assertEqual(_ids(chosen), ["b", "a"])

    def test_longer_number_in_the_chunk_is_not_a_match(self):
        hits = [_hit("12016 and 20160", 0.9, "a"), _hit("in 2016", 0.2, "b")]
        search = _Search(hits)
        chosen = retrieve_naive_hits("the 2016 season", search, j2_enabled=True)
        self.assertEqual(_ids(chosen), ["b", "a"])


if __name__ == "__main__":
    unittest.main()
