"""Offline test for survey_candidates.py: synthetic fixtures only (never
the real corpus or the real golden-set draft), no network, no model call,
no search system, no database. Run with:

    python -m unittest diagnostics/2026-11-11-week5-a2/test_survey_candidates_offline.py -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import survey_candidates as sc

FIXTURE_CHUNKS = [
    {"chunk_id": "doc-a#0", "doc_id": "doc-a", "ordinal": 0, "section": "Doc A", "page": 1,
     "n_chars": 40, "text": "Alpha driver won seven championships with Team Red.", "chunk_size": 40, "chunk_overlap": 0},
    {"chunk_id": "doc-a#1", "doc_id": "doc-a", "ordinal": 1, "section": "Doc A", "page": 2,
     "n_chars": 20, "text": "Unrelated filler text about weather.", "chunk_size": 20, "chunk_overlap": 0},
    {"chunk_id": "doc-b#0", "doc_id": "doc-b", "ordinal": 0, "section": "Doc B", "page": 1,
     "n_chars": 30, "text": "Beta driver joined Team Red in 2015 after leaving Team Blue.", "chunk_size": 30, "chunk_overlap": 0},
    {"chunk_id": "doc-c#0", "doc_id": "doc-c", "ordinal": 0, "section": "Doc C", "page": 1,
     "n_chars": 25, "text": "Team Blue history and constructors standings overview.", "chunk_size": 25, "chunk_overlap": 0},
    {"chunk_id": "doc-d#0", "doc_id": "doc-d", "ordinal": 0, "section": "Doc D", "page": 1,
     "n_chars": 25, "text": "Gamma driver finished third in the championship in 2016.", "chunk_size": 25, "chunk_overlap": 0},
    {"chunk_id": "doc-e#0", "doc_id": "doc-e", "ordinal": 0, "section": "Doc E", "page": 1,
     "n_chars": 25, "text": "Delta driver raced for Team Green from 2010 to 2013.", "chunk_size": 25, "chunk_overlap": 0},
    {"chunk_id": "doc-f#0", "doc_id": "doc-f", "ordinal": 0, "section": "Doc F", "page": 1,
     "n_chars": 25, "text": "Epsilon season summary with several technical notes.", "chunk_size": 25, "chunk_overlap": 0},
    {"chunk_id": "doc-g#0", "doc_id": "doc-g", "ordinal": 0, "section": "Doc G", "page": 1,
     "n_chars": 25, "text": "Zeta team factory and headquarters location overview.", "chunk_size": 25, "chunk_overlap": 0},
    {"chunk_id": "doc-h#0", "doc_id": "doc-h", "ordinal": 0, "section": "Doc H", "page": 1,
     "n_chars": 25, "text": "Eta reference document about regulations history.", "chunk_size": 25, "chunk_overlap": 0},
    {"chunk_id": "doc-i#0", "doc_id": "doc-i", "ordinal": 0, "section": "Doc I", "page": 1,
     "n_chars": 25, "text": "Theta season championship standings for the decade.", "chunk_size": 25, "chunk_overlap": 0},
    {"chunk_id": "doc-j#0", "doc_id": "doc-j", "ordinal": 0, "section": "Doc J", "page": 1,
     "n_chars": 25, "text": "Iota team sponsorship and livery history overview.", "chunk_size": 25, "chunk_overlap": 0},
]

FIXTURE_QUESTIONS = [
    {
        "id": "F01", "question": "Which team did Beta driver join in 2015?",
        "criteria": [{"id": "F01-c1", "expected_content": ["Team Red", "2015"]}],
    },
    {
        "id": "F02", "question": "Open question with no criteria at all.",
        "criteria": [],
    },
]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class LoadTests(unittest.TestCase):
    def test_load_chunks_requires_core_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chunks.jsonl"
            path.write_text('{"doc_id": "x", "text": "y"}\n', encoding="utf-8")
            with self.assertRaises(sc.SurveyError):
                sc.load_chunks(path)

    def test_load_chunks_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chunks.jsonl"
            _write_jsonl(path, FIXTURE_CHUNKS)
            rows = sc.load_chunks(path)
            self.assertEqual(len(rows), len(FIXTURE_CHUNKS))

    def test_load_questions_requires_id_and_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.jsonl"
            path.write_text('{"id": "Q01"}\n', encoding="utf-8")
            with self.assertRaises(sc.SurveyError):
                sc.load_questions(path)


class TermExtractionTests(unittest.TestCase):
    def test_terms_come_from_criteria_when_present(self) -> None:
        terms, source = sc.question_terms(FIXTURE_QUESTIONS[0])
        self.assertIn("team", terms)
        self.assertIn("red", terms)
        self.assertIn("2015", terms)
        self.assertEqual(source, "criteria.expected_content")

    def test_terms_fall_back_to_question_text_when_criteria_empty(self) -> None:
        terms, source = sc.question_terms(FIXTURE_QUESTIONS[1])
        self.assertTrue(terms)
        self.assertIn("question_text_fallback", source)

    def test_stopwords_and_short_tokens_excluded(self) -> None:
        terms, _source = sc.question_terms({
            "question": "the of a to", "criteria": [],
        })
        self.assertEqual(terms, [])

    def test_short_numeric_terms_are_kept(self) -> None:
        terms, _source = sc.question_terms({
            "question": "placeholder",
            "criteria": [{"expected_content": ["Lewis Hamilton", "7"]}],
        })
        self.assertIn("7", terms)


class SearchCandidatesTests(unittest.TestCase):
    def test_candidates_are_marked_as_candidates_not_gold(self) -> None:
        result = sc.search_candidates(FIXTURE_QUESTIONS, FIXTURE_CHUNKS, top_n=3)
        q1 = next(r for r in result if r["question_id"] == "F01")
        self.assertIn("candidates", q1)
        self.assertEqual(q1["note"], "keyword candidates only, not gold chunk ids")
        top_chunk_ids = [c["chunk_id"] for c in q1["candidates"]]
        self.assertIn("doc-b#0", top_chunk_ids)

    def test_top_n_is_respected(self) -> None:
        result = sc.search_candidates(FIXTURE_QUESTIONS, FIXTURE_CHUNKS, top_n=1)
        q1 = next(r for r in result if r["question_id"] == "F01")
        self.assertLessEqual(len(q1["candidates"]), 1)

    def test_zero_score_chunks_are_not_returned(self) -> None:
        result = sc.search_candidates(FIXTURE_QUESTIONS, FIXTURE_CHUNKS, top_n=100)
        q1 = next(r for r in result if r["question_id"] == "F01")
        for candidate in q1["candidates"]:
            self.assertGreater(candidate["score"], 0)

    def test_search_is_deterministic_across_runs(self) -> None:
        first = sc.search_candidates(FIXTURE_QUESTIONS, FIXTURE_CHUNKS, top_n=3)
        second = sc.search_candidates(FIXTURE_QUESTIONS, FIXTURE_CHUNKS, top_n=3)
        self.assertEqual(first, second)


class SnippetTests(unittest.TestCase):
    def test_short_text_returned_whole(self) -> None:
        text = "Short text."
        self.assertEqual(sc.make_snippet(text, ["short"]), text)

    def test_long_text_windowed_around_term(self) -> None:
        text = "x" * 500 + "NEEDLE" + "y" * 500
        snippet = sc.make_snippet(text, ["needle"], window=20)
        self.assertIn("NEEDLE", snippet)
        self.assertLess(len(snippet), len(text))


class SampleTests(unittest.TestCase):
    def test_sample_size_and_distinct_documents(self) -> None:
        sample = sc.sample_one_chunk_per_doc(FIXTURE_CHUNKS, seed=42, sample_size=5)
        self.assertEqual(len(sample), 5)
        doc_ids = [row["doc_id"] for row in sample]
        self.assertEqual(len(doc_ids), len(set(doc_ids)))

    def test_sample_is_reproducible_with_same_seed(self) -> None:
        first = sc.sample_one_chunk_per_doc(FIXTURE_CHUNKS, seed=42, sample_size=5)
        second = sc.sample_one_chunk_per_doc(FIXTURE_CHUNKS, seed=42, sample_size=5)
        self.assertEqual(first, second)

    def test_sample_changes_with_different_seed(self) -> None:
        first = sc.sample_one_chunk_per_doc(FIXTURE_CHUNKS, seed=42, sample_size=5)
        other = sc.sample_one_chunk_per_doc(FIXTURE_CHUNKS, seed=7, sample_size=5)
        self.assertNotEqual(
            [row["doc_id"] for row in first], [row["doc_id"] for row in other])

    def test_sample_raises_when_not_enough_documents(self) -> None:
        with self.assertRaises(sc.SurveyError):
            sc.sample_one_chunk_per_doc(FIXTURE_CHUNKS, seed=42, sample_size=50)

    def test_sample_rows_carry_full_chunk_fields(self) -> None:
        sample = sc.sample_one_chunk_per_doc(FIXTURE_CHUNKS, seed=42, sample_size=3)
        for row in sample:
            self.assertIn("text", row)
            self.assertIn("chunk_id", row)
            self.assertIn("ordinal", row)


class CorpusHashTests(unittest.TestCase):
    def test_hash_is_stable_for_same_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chunks.jsonl"
            _write_jsonl(path, FIXTURE_CHUNKS)
            first = sc.corpus_sha256(path)
            second = sc.corpus_sha256(path)
            self.assertEqual(first, second)
            self.assertEqual(len(first), 64)


class CliEndToEndTests(unittest.TestCase):
    """Runs the actual subcommands against temp files, never the real
    corpus or the real golden-set draft."""

    def test_search_subcommand_writes_expected_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            chunks_path = tmp_path / "chunks.jsonl"
            golden_path = tmp_path / "golden.jsonl"
            out_path = tmp_path / "out-search.json"
            _write_jsonl(chunks_path, FIXTURE_CHUNKS)
            _write_jsonl(golden_path, FIXTURE_QUESTIONS)
            rc = sc.main(["search", "--chunks", str(chunks_path),
                         "--golden", str(golden_path), "--out", str(out_path)])
            self.assertEqual(rc, 0)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["chunk_count"], len(FIXTURE_CHUNKS))
            self.assertEqual(payload["question_count"], len(FIXTURE_QUESTIONS))
            self.assertEqual(len(payload["corpus_sha256"]), 64)
            self.assertIn("questions", payload)

    def test_sample_subcommand_writes_expected_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            chunks_path = tmp_path / "chunks.jsonl"
            out_path = tmp_path / "out-sample.json"
            _write_jsonl(chunks_path, FIXTURE_CHUNKS)
            rc = sc.main(["sample", "--chunks", str(chunks_path),
                         "--out", str(out_path), "--size", "5"])
            self.assertEqual(rc, 0)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["seed"], 42)
            self.assertEqual(payload["sample_size"], 5)
            self.assertEqual(len(payload["sample"]), 5)


if __name__ == "__main__":
    unittest.main()
