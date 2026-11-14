"""Database-free, model-free checks for the Phase 4 map-reduce global search.

No Neo4j connection, no OpenAI call. The "model" is a fake callable built
per test. The Leiden algorithm and report generation are never invoked.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from naive_rag import global_search as gs

RUN_ID = "week4-leiden-elokeszitett-6f05327d7d88ebf0"


def _report_row(path: str, statements: list[dict]) -> dict:
    return {
        "community_id": f"{RUN_ID}:{path}",
        "path": path,
        "run_id": RUN_ID,
        "reporting_level": 0,
        "prompt_version": "riportprompt-v3",
        "summary": f"Summary for community {path}.",
        "key_statements": statements,
        "validation": {"valid_structure": True, "problems": [], "unknown_record_ids": []},
    }


def _write_collection(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _sample_reports_file(tmp_path: Path) -> Path:
    rows = [
        _report_row("5", [
            {"statement": "Driver X won the championship.", "evidence_ids": ["N001"],
             "candidate_source_chunk_ids": ["doc-a#1", "doc-a#2"]},
        ]),
        _report_row("22", [
            {"statement": "Team Y fielded car Z.", "evidence_ids": ["E001"],
             "candidate_source_chunk_ids": ["doc-b#5"]},
        ]),
    ]
    path = tmp_path / "collection.jsonl"
    _write_collection(path, rows)
    return path


class ReportLoadingTests(unittest.TestCase):
    def test_loads_statements_with_stable_ids_in_path_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _sample_reports_file(Path(tmp))
            reports = gs.load_reports(path, expected_run_id=RUN_ID)
        self.assertEqual([r.path for r in reports], ["5", "22"])
        self.assertEqual(reports[0].statements[0].statement_id, "5#1")
        self.assertEqual(reports[0].statements[0].evidence_ids, ("N001",))

    def test_rejects_wrong_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _sample_reports_file(Path(tmp))
            with self.assertRaises(gs.GlobalSearchError):
                gs.load_reports(path, expected_run_id="some-other-run")

    def test_rejects_unvalidated_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = _report_row("5", [{"statement": "x", "evidence_ids": ["N001"],
                                      "candidate_source_chunk_ids": []}])
            row["validation"]["valid_structure"] = False
            path = Path(tmp) / "collection.jsonl"
            _write_collection(path, [row])
            with self.assertRaises(gs.GlobalSearchError):
                gs.load_reports(path, expected_run_id=RUN_ID)

    def test_rejects_duplicate_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = _report_row("5", [{"statement": "x", "evidence_ids": [], "candidate_source_chunk_ids": []}])
            path = Path(tmp) / "collection.jsonl"
            _write_collection(path, [row, row])
            with self.assertRaises(gs.GlobalSearchError):
                gs.load_reports(path, expected_run_id=RUN_ID)


class QuestionLoadingTests(unittest.TestCase):
    def test_reads_label_from_file_not_guessed_from_id(self):
        text = (
            "## simple\n\n### Q01 — simple\n**Kérdés:** A?\n\n"
            "## global\n\n### Q09 — global\n**Kérdés:** B?\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "questions.md"
            path.write_text(text, encoding="utf-8")
            questions = gs.load_questions(path)
        self.assertEqual([(q.question_id, q.label) for q in questions],
                         [("Q01", "simple"), ("Q09", "global")])
        globals_ = gs.questions_by_label(questions, "global")
        self.assertEqual([q.question_id for q in globals_], ["Q09"])
        self.assertEqual(globals_[0].text, "B?")


class MapValidationTests(unittest.TestCase):
    def setUp(self):
        self.report = gs.CommunityReport(
            path="5", community_id=f"{RUN_ID}:5", run_id=RUN_ID, reporting_level=0,
            summary="s",
            statements=(gs.ReportStatement("5#1", "stmt", ("N001",), ("doc#1",)),),
        )

    def test_valid_positive_score(self):
        parsed = {"partial_answer": "x", "usefulness_score": 80, "cited_statement_ids": ["5#1"]}
        v = gs.validate_map_response(parsed, self.report)
        self.assertTrue(v.valid_structure)

    def test_valid_zero_score_with_empty_fields(self):
        parsed = {"partial_answer": "", "usefulness_score": 0, "cited_statement_ids": []}
        v = gs.validate_map_response(parsed, self.report)
        self.assertTrue(v.valid_structure)

    def test_positive_score_requires_nonempty_answer_and_citation(self):
        parsed = {"partial_answer": "", "usefulness_score": 50, "cited_statement_ids": []}
        v = gs.validate_map_response(parsed, self.report)
        self.assertFalse(v.valid_structure)
        self.assertTrue(any("empty partial_answer" in p for p in v.problems))
        self.assertTrue(any("empty cited_statement_ids" in p for p in v.problems))

    def test_unknown_statement_id_is_rejected(self):
        parsed = {"partial_answer": "x", "usefulness_score": 10, "cited_statement_ids": ["99#1"]}
        v = gs.validate_map_response(parsed, self.report)
        self.assertFalse(v.valid_structure)
        self.assertEqual(v.unknown_statement_ids, ("99#1",))

    def test_score_out_of_range_rejected(self):
        parsed = {"partial_answer": "x", "usefulness_score": 150, "cited_statement_ids": ["5#1"]}
        v = gs.validate_map_response(parsed, self.report)
        self.assertFalse(v.valid_structure)

    def test_score_must_be_int_not_bool(self):
        parsed = {"partial_answer": "", "usefulness_score": True, "cited_statement_ids": []}
        v = gs.validate_map_response(parsed, self.report)
        self.assertFalse(v.valid_structure)


class SelectionOrderingTests(unittest.TestCase):
    def test_positive_only_filters_and_sorts_deterministically(self):
        results = [
            gs.MapResult("22", "Q09", "a", 0, ()),
            gs.MapResult("5", "Q09", "b", 50, ("5#1",)),
            gs.MapResult("205", "Q09", "c", 50, ("205#1",)),  # tie on score -> path tuple order
            gs.MapResult("3", "Q09", "d", 90, ("3#1",)),
        ]
        basis = gs.select_basis(results, include_zero=False)
        self.assertEqual([r.path for r in basis], ["3", "5", "205"])

    def test_include_zero_keeps_zero_score_entries(self):
        results = [gs.MapResult("5", "Q09", "", 0, ()), gs.MapResult("3", "Q09", "x", 10, ("3#1",))]
        basis = gs.select_basis(results, include_zero=True)
        self.assertEqual([r.path for r in basis], ["3", "5"])

    def test_path_sorted_numerically_not_lexically(self):
        results = [gs.MapResult("22", "Q09", "x", 10, ("a",)), gs.MapResult("5", "Q09", "y", 10, ("b",))]
        basis = gs.select_basis(results, include_zero=False)
        self.assertEqual([r.path for r in basis], ["5", "22"])


class AllZeroRefusalTests(unittest.TestCase):
    def test_all_zero_scores_refuse_without_model_call(self):
        question = gs.Question("Q09", "global", "Who won the most titles?")
        reports = (
            gs.CommunityReport("5", f"{RUN_ID}:5", RUN_ID, 0, "s",
                               (gs.ReportStatement("5#1", "x", (), ()),)),
        )

        calls = []

        def fake_call(system, user, max_tokens):
            calls.append((system, user, max_tokens))
            payload = json.loads(user)
            if "partial_answers" in payload:
                # B's basis is non-empty (one zero-score entry) and differs
                # from A's empty basis, so B does make a real reduce call.
                return gs.ModelResponse(
                    content=json.dumps({"answer": "Not enough evidence in the zero-score partial.",
                                        "cited_partial_answer_ids": []}),
                    returned_model="gpt-4o-mini-test", usage_prompt_tokens=10, usage_completion_tokens=5,
                    finish_reason="stop",
                )
            return gs.ModelResponse(
                content=json.dumps({"partial_answer": "", "usefulness_score": 0, "cited_statement_ids": []}),
                returned_model="gpt-4o-mini-test", usage_prompt_tokens=10, usage_completion_tokens=5,
                finish_reason="stop",
            )

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            ledger_path = Path(tmp) / "ledger.json"
            outcome = gs.run_phase4([question], reports, fake_call, out_dir=out_dir, ledger_path=ledger_path)

        self.assertIsNone(outcome["halted_reason"])
        result = outcome["questions"]["Q09"]
        # A refuses without any model call (no positive-score partial exists)
        self.assertEqual(result["reduce_a"]["answer"], gs.GLOBAL_REFUSAL)
        self.assertTrue(result["reduce_a"].get("no_model_call"))
        # B's basis (the zero-score entry) differs from A's (empty), so B
        # IS a real call -- exactly one reduce call total, not zero.
        reduce_calls = [c for c in calls if "partial_answers" in c[1]]
        self.assertEqual(len(reduce_calls), 1)
        self.assertFalse(result["reduce_b"].get("no_model_call", False))


class ReduceReuseTests(unittest.TestCase):
    def _reports(self):
        return (
            gs.CommunityReport("5", f"{RUN_ID}:5", RUN_ID, 0, "s",
                               (gs.ReportStatement("5#1", "x", (), ()),)),
            gs.CommunityReport("22", f"{RUN_ID}:22", RUN_ID, 0, "s",
                               (gs.ReportStatement("22#1", "y", (), ()),)),
        )

    def test_identical_basis_skips_the_second_reduce_call(self):
        """All scores positive -> basis A == basis B -> B must not call the model."""
        question = gs.Question("Q09", "global", "Q?")
        reports = self._reports()
        reduce_calls = []

        def fake_call(system, user, max_tokens):
            payload = json.loads(user)
            if "partial_answers" in payload:
                reduce_calls.append(payload)
                return gs.ModelResponse(
                    content=json.dumps({"answer": "final", "cited_partial_answer_ids": ["5", "22"]}),
                    returned_model="m", usage_prompt_tokens=10, usage_completion_tokens=5, finish_reason="stop",
                )
            path = payload["statements"][0]["id"].split("#")[0]
            return gs.ModelResponse(
                content=json.dumps({"partial_answer": f"ans-{path}", "usefulness_score": 60,
                                    "cited_statement_ids": [payload["statements"][0]["id"]]}),
                returned_model="m", usage_prompt_tokens=10, usage_completion_tokens=5, finish_reason="stop",
            )

        with tempfile.TemporaryDirectory() as tmp:
            out_dir, ledger_path = Path(tmp) / "out", Path(tmp) / "ledger.json"
            outcome = gs.run_phase4([question], reports, fake_call, out_dir=out_dir, ledger_path=ledger_path)

        self.assertIsNone(outcome["halted_reason"])
        self.assertEqual(len(reduce_calls), 1)  # only A called a real reduce; B reused it
        result = outcome["questions"]["Q09"]
        self.assertEqual(result["reduce_b"]["answer"], result["reduce_a"]["answer"])
        self.assertTrue(result["reduce_b"].get("no_model_call"))

    def test_mixed_scores_call_reduce_twice_with_reused_map_results(self):
        question = gs.Question("Q09", "global", "Q?")
        reports = self._reports()
        map_call_count = 0
        reduce_payloads = []

        def fake_call(system, user, max_tokens):
            nonlocal map_call_count
            payload = json.loads(user)
            if "partial_answers" in payload:
                reduce_payloads.append(payload)
                return gs.ModelResponse(
                    content=json.dumps({"answer": "final", "cited_partial_answer_ids": [p["id"] for p in payload["partial_answers"]]}),
                    returned_model="m", usage_prompt_tokens=10, usage_completion_tokens=5, finish_reason="stop",
                )
            map_call_count += 1
            sid = payload["statements"][0]["id"]
            path = sid.split("#")[0]
            score = 60 if path == "5" else 0
            cited = [sid] if score else []
            return gs.ModelResponse(
                content=json.dumps({"partial_answer": "ans" if score else "", "usefulness_score": score,
                                    "cited_statement_ids": cited}),
                returned_model="m", usage_prompt_tokens=10, usage_completion_tokens=5, finish_reason="stop",
            )

        with tempfile.TemporaryDirectory() as tmp:
            out_dir, ledger_path = Path(tmp) / "out", Path(tmp) / "ledger.json"
            outcome = gs.run_phase4([question], reports, fake_call, out_dir=out_dir, ledger_path=ledger_path)

        self.assertIsNone(outcome["halted_reason"])
        self.assertEqual(map_call_count, 2)  # one per report, never repeated between A/B
        self.assertEqual(len(reduce_payloads), 2)  # A (1 partial) and B (2 partials) differ -> both called
        self.assertEqual(len(reduce_payloads[0]["partial_answers"]), 1)
        self.assertEqual(len(reduce_payloads[1]["partial_answers"]), 2)


class LedgerResumabilityTests(unittest.TestCase):
    def test_in_progress_entry_halts_without_any_call(self):
        question = gs.Question("Q09", "global", "Q?")
        reports = (gs.CommunityReport("5", f"{RUN_ID}:5", RUN_ID, 0, "s",
                                      (gs.ReportStatement("5#1", "x", (), ()),)),)

        def fake_call(system, user, max_tokens):
            raise AssertionError("must not be called when a ledger entry is in_progress")

        with tempfile.TemporaryDirectory() as tmp:
            out_dir, ledger_path = Path(tmp) / "out", Path(tmp) / "ledger.json"
            out_dir.mkdir()
            ledger_path.write_text(json.dumps({"map:Q09:5": {"status": "in_progress"}}), encoding="utf-8")
            outcome = gs.run_phase4([question], reports, fake_call, out_dir=out_dir, ledger_path=ledger_path)

        self.assertIsNotNone(outcome["halted_reason"])
        self.assertIn("uncertain", outcome["halted_reason"])

    def test_already_attempted_map_is_not_called_again(self):
        question = gs.Question("Q09", "global", "Q?")
        reports = (gs.CommunityReport("5", f"{RUN_ID}:5", RUN_ID, 0, "s",
                                      (gs.ReportStatement("5#1", "x", (), ()),)),)

        with tempfile.TemporaryDirectory() as tmp:
            out_dir, ledger_path = Path(tmp) / "out", Path(tmp) / "ledger.json"
            out_dir.mkdir()
            saved = {"community_path": "5", "question_id": "Q09", "partial_answer": "cached",
                     "usefulness_score": 70, "cited_statement_ids": ["5#1"],
                     "validation": {"valid_structure": True, "problems": [], "unknown_statement_ids": []}}
            (out_dir / "map-result-Q09-5.json").write_text(json.dumps(saved), encoding="utf-8")
            ledger_path.write_text(json.dumps({"map:Q09:5": {"status": "success"}}), encoding="utf-8")

            calls = []

            def fake_call(system, user, max_tokens):
                calls.append(user)
                return gs.ModelResponse(
                    content=json.dumps({"answer": "final", "cited_partial_answer_ids": ["5"]}),
                    returned_model="m", usage_prompt_tokens=1, usage_completion_tokens=1, finish_reason="stop",
                )

            outcome = gs.run_phase4([question], reports, fake_call, out_dir=out_dir, ledger_path=ledger_path)

        self.assertIsNone(outcome["halted_reason"])
        # only the reduce call should have happened; the map must reuse the cached file
        self.assertEqual(len(calls), 1)
        self.assertIn("partial_answers", calls[0])
        self.assertEqual(outcome["questions"]["Q09"]["map_results"][0].partial_answer, "cached")


class FailureHaltsTests(unittest.TestCase):
    def test_invalid_map_response_halts_the_whole_run(self):
        question = gs.Question("Q09", "global", "Q?")
        reports = (
            gs.CommunityReport("5", f"{RUN_ID}:5", RUN_ID, 0, "s", (gs.ReportStatement("5#1", "x", (), ()),)),
            gs.CommunityReport("22", f"{RUN_ID}:22", RUN_ID, 0, "s", (gs.ReportStatement("22#1", "y", (), ()),)),
        )
        calls = []

        def fake_call(system, user, max_tokens):
            calls.append(user)
            if len(calls) == 1:
                # positive score but empty citation -> invalid
                return gs.ModelResponse(
                    content=json.dumps({"partial_answer": "x", "usefulness_score": 10, "cited_statement_ids": []}),
                    returned_model="m", usage_prompt_tokens=1, usage_completion_tokens=1, finish_reason="stop",
                )
            raise AssertionError("must stop after the first invalid map response")

        with tempfile.TemporaryDirectory() as tmp:
            out_dir, ledger_path = Path(tmp) / "out", Path(tmp) / "ledger.json"
            outcome = gs.run_phase4([question], reports, fake_call, out_dir=out_dir, ledger_path=ledger_path)

        self.assertIsNotNone(outcome["halted_reason"])
        self.assertEqual(len(calls), 1)

    def test_api_error_halts_and_is_recorded(self):
        question = gs.Question("Q09", "global", "Q?")
        reports = (gs.CommunityReport("5", f"{RUN_ID}:5", RUN_ID, 0, "s", (gs.ReportStatement("5#1", "x", (), ()),)),)

        def fake_call(system, user, max_tokens):
            raise RuntimeError("simulated API failure")

        with tempfile.TemporaryDirectory() as tmp:
            out_dir, ledger_path = Path(tmp) / "out", Path(tmp) / "ledger.json"
            outcome = gs.run_phase4([question], reports, fake_call, out_dir=out_dir, ledger_path=ledger_path)
            ledger = gs.load_ledger(ledger_path)

        self.assertIsNotNone(outcome["halted_reason"])
        self.assertEqual(ledger["map:Q09:5"]["status"], "error")


class ContextWindowTests(unittest.TestCase):
    def test_oversized_reduce_input_raises_without_calling(self):
        huge = "x" * (gs.ASSUMED_REDUCE_CONTEXT_WINDOW_TOKENS * 5)
        with self.assertRaises(gs.ContextWindowExceeded):
            gs.check_reduce_context_fits(gs.REDUCE_SYSTEM_PROMPT, huge)

    def test_normal_sized_input_passes(self):
        estimate = gs.check_reduce_context_fits(gs.REDUCE_SYSTEM_PROMPT, "short input")
        self.assertIsInstance(estimate, int)


class CitationChainTests(unittest.TestCase):
    def test_chain_resolves_statement_and_evidence(self):
        report = gs.CommunityReport("5", f"{RUN_ID}:5", RUN_ID, 0, "s",
                                    (gs.ReportStatement("5#1", "Driver X won.", ("N001",), ("doc#1", "doc#2")),))
        map_result = gs.MapResult("5", "Q09", "Driver X won the championship.", 80, ("5#1",))
        chain = gs.resolve_citation_chain(["5"], {"5": map_result}, {"5": report})
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["statements"][0]["evidence_ids"], ["N001"])
        self.assertEqual(chain[0]["statements"][0]["candidate_source_chunk_ids"], ["doc#1", "doc#2"])


class RealQuestionsFileTests(unittest.TestCase):
    """Sanity check against the real repo question file (read-only)."""

    def test_real_questions_md_has_five_global_questions(self):
        path = Path(__file__).resolve().parents[1] / "questions.md"
        questions = gs.load_questions(path)
        globals_ = gs.questions_by_label(questions, "global")
        self.assertEqual([q.question_id for q in globals_], ["Q09", "Q10", "Q11", "Q12", "Q13"])
        for q in globals_:
            self.assertTrue(q.text)


if __name__ == "__main__":
    unittest.main()
