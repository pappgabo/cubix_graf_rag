"""Offline, no-real-call checks for the week6 drift measurement
orchestration (`drift_measure.py`). Reuses week5-b's own `process_case`/
`CaseContext` unchanged -- these tests prove our thin, single-mode wiring
around them behaves like the task requires, not that `process_case` works
(week5-b's own test suite already covers that)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import week6_bootstrap  # noqa: F401,E402
import drift_measure as dm  # noqa: E402
import golden_set as gs  # noqa: E402
import measure as week5measure  # noqa: E402
import state_store as ss  # noqa: E402

ROW = {
    "id": "X01", "type": "simple", "status": "frozen_w4", "question": "Q?",
    "expected_answer": "SECRET-GOLD-ANSWER", "criteria": [
        {"id": "X01-c1", "text": "t1", "expected_content": ["a"], "required": True}],
    "evidence_groups": [{"id": "X01-e1", "criterion": "X01-c1", "any_of_chunk_ids": ["doc-a#0"]}],
    "gold_docs": ["doc-a"], "notes": "n", "golden_set_version": "test",
    "corpus": {"chunks_file": "x", "chunks_sha256": "abc", "chunk_count": 2},
}


def _questions(ids: tuple[str, ...]) -> list[gs.GoldenQuestion]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "g.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for qid in ids:
                handle.write(json.dumps({**ROW, "id": qid}) + "\n")
        return list(gs.load_golden_set(path))


def _make_ctx(case_dir: Path, *, drift_calls: list, fail_at: str | None = None,
             seen_inputs: list | None = None) -> week5measure.CaseContext:
    def drift_fn(question):
        drift_calls.append(question.id)
        if seen_inputs is not None:
            seen_inputs.append((question.id, question.question))
        if fail_at == "answer_saved":
            return {"error": "simulated drift failure"}
        return {
            "question_id": question.id, "mode": "drift", "run_phase": "smoke",
            "answer": "drift answer", "refused": False, "model_called": True,
            "actual_context": "ctx", "actual_chunk_ids": ["doc-a#0"], "chunk_ids_traceable": True,
            "is_proxy_retrieval": False, "error": None, "duration_seconds": 0.1,
        }

    def correctness_call_fn(system, user, max_tokens):
        if fail_at == "criteria_scored":
            raise RuntimeError("simulated judge failure")
        from dataclasses import dataclass

        @dataclass
        class R:
            content: str
            returned_model: str = "fake"
            usage_prompt_tokens: object = 10
            usage_completion_tokens: object = 5
            finish_reason: str = "stop"

        return R(content=json.dumps({
            "criteria": [{"criterion_id": "X01-c1", "verdict": "met", "explanation": "ok"}],
            "refused": False, "rubric_conflicts": [], "reasoning": "ok",
        }))

    def faithfulness_call_fn(system, user, max_tokens):
        from dataclasses import dataclass

        @dataclass
        class R:
            content: str
            returned_model: str = "fake"
            usage_prompt_tokens: object = 10
            usage_completion_tokens: object = 5
            finish_reason: str = "stop"

        return R(content=json.dumps({
            "claims": [{"claim": "doc-a#0 content", "verdict": "supported"}], "reasoning": "ok",
        }))

    return week5measure.CaseContext(
        run_phase="smoke", budget=None, ledger=None, gen_fns={"drift": drift_fn},
        correctness_call_fn_factory=lambda qid, mode, step: correctness_call_fn,
        faithfulness_call_fn_factory=lambda qid, mode, step: faithfulness_call_fn,
        langfuse_sync_fn=None, case_store_dir=case_dir,
    )


class SelectQuestionsTests(unittest.TestCase):
    def test_smoke_is_exactly_q01_q07_q10(self) -> None:
        all_q = _questions(("Q01", "Q02", "Q07", "Q10", "Q11"))
        smoke = dm.select_questions(all_q, "smoke")
        self.assertEqual({q.id for q in smoke}, {"Q01", "Q07", "Q10"})

    def test_smoke_raises_if_a_required_id_is_missing(self) -> None:
        all_q = _questions(("Q01", "Q02"))
        with self.assertRaises(ValueError):
            dm.select_questions(all_q, "smoke")

    def test_full_returns_all_fifteen(self) -> None:
        all_q = _questions(tuple(f"Q{i:02d}" for i in range(1, 16)))
        full = dm.select_questions(all_q, "full")
        self.assertEqual(len(full), 15)


class RunDriftCasesTests(unittest.TestCase):
    def test_only_drift_mode_cases_are_created(self) -> None:
        questions = _questions(("Q01", "Q07", "Q10"))
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            sig = ss.RunSignature(run_kind="smoke", config_sha256="c", golden_set_sha256="g")
            store = ss.StateStore(path=case_dir / "state.json", signature=sig)
            drift_calls: list = []
            ctx = _make_ctx(case_dir, drift_calls=drift_calls)
            rows = dm.run_drift_cases(questions, store, ctx)
            self.assertEqual(len(rows), 3)
            self.assertEqual({row["mode"] for row in rows}, {"drift"})
            for qid in ("Q01", "Q07", "Q10"):
                self.assertTrue((case_dir / f"{qid}-drift.json").exists())
                self.assertFalse((case_dir / f"{qid}-naiv.json").exists())
                self.assertFalse((case_dir / f"{qid}-lokalis.json").exists())
                self.assertFalse((case_dir / f"{qid}-globalis.json").exists())

    def test_full_set_is_fifteen_cases(self) -> None:
        questions = _questions(tuple(f"Q{i:02d}" for i in range(1, 16)))
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            sig = ss.RunSignature(run_kind="full", config_sha256="c", golden_set_sha256="g")
            store = ss.StateStore(path=case_dir / "state.json", signature=sig)
            drift_calls: list = []
            ctx = _make_ctx(case_dir, drift_calls=drift_calls)
            rows = dm.run_drift_cases(questions, store, ctx)
            self.assertEqual(len(rows), 15)
            self.assertEqual(len(drift_calls), 15)

    def test_already_saved_answer_and_judges_are_not_rerun_on_resume(self) -> None:
        questions = _questions(("Q01",))
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            sig = ss.RunSignature(run_kind="smoke", config_sha256="c", golden_set_sha256="g")
            store = ss.StateStore(path=case_dir / "state.json", signature=sig)
            drift_calls: list = []
            ctx = _make_ctx(case_dir, drift_calls=drift_calls)
            dm.run_drift_cases(questions, store, ctx)
            self.assertEqual(len(drift_calls), 1)

            # a fresh store object, loaded back from disk (a real resume)
            store2 = ss.StateStore.load_or_create(case_dir / "state.json", sig)
            drift_calls2: list = []
            ctx2 = _make_ctx(case_dir, drift_calls=drift_calls2)
            rows2 = dm.run_drift_cases(questions, store2, ctx2)
            self.assertEqual(drift_calls2, [])  # generation NOT re-run
            self.assertEqual(rows2[0]["correctness"]["label"], "helyes")
            self.assertIsNotNone(rows2[0]["faithfulness"]["score"])

    def test_generation_error_halts_the_whole_run(self) -> None:
        questions = _questions(("Q01", "Q07"))
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            sig = ss.RunSignature(run_kind="smoke", config_sha256="c", golden_set_sha256="g")
            store = ss.StateStore(path=case_dir / "state.json", signature=sig)
            drift_calls: list = []
            ctx = _make_ctx(case_dir, drift_calls=drift_calls, fail_at="answer_saved")
            with self.assertRaises(week5measure.MeasurementHalted):
                dm.run_drift_cases(questions, store, ctx)
            self.assertEqual(drift_calls, ["Q01"])  # Q07 never attempted

    def test_golden_answer_and_criteria_never_reach_the_gen_fn_input(self) -> None:
        """`drift_fn` only ever sees `question.question` -- the golden
        `expected_answer`/`criteria` are on the `GoldenQuestion` object but
        the gen_fn signature (`question.question`) never routes them into
        the search/generation input."""
        questions = _questions(("Q01",))
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            sig = ss.RunSignature(run_kind="smoke", config_sha256="c", golden_set_sha256="g")
            store = ss.StateStore(path=case_dir / "state.json", signature=sig)
            seen_inputs: list = []
            ctx = _make_ctx(case_dir, drift_calls=[], seen_inputs=seen_inputs)
            dm.run_drift_cases(questions, store, ctx)
            self.assertEqual(seen_inputs, [("Q01", "Q?")])
            for _qid, question_text in seen_inputs:
                self.assertNotIn("SECRET-GOLD-ANSWER", question_text)


class ReportIndexNotReadyTests(unittest.TestCase):
    def test_missing_cache_raises_before_any_case_runs(self) -> None:
        from naive_rag.global_search import CommunityReport, ReportStatement

        reports = (
            CommunityReport(
                path="1", community_id="c1", run_id="r", reporting_level=0,
                summary="s", statements=(ReportStatement("1#1", "t", (), ()),)),
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "missing.json"
            with self.assertRaises(dm.ReportIndexNotReady):
                dm.require_report_index(reports, cache_path)


class RunSignatureResumeTests(unittest.TestCase):
    def test_different_report_index_hash_is_a_different_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            golden_path = Path(tmp) / "g.jsonl"
            golden_path.write_text(json.dumps(ROW) + "\n", encoding="utf-8")
            sig_a = dm.build_run_signature(
                "smoke", golden_path, global_run_id="run-a", reports_hash="hash-a")
            sig_b = dm.build_run_signature(
                "smoke", golden_path, global_run_id="run-a", reports_hash="hash-b")
            self.assertNotEqual(sig_a.config_sha256, sig_b.config_sha256)

    def test_mismatched_signature_refuses_to_resume_silently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            golden_path = Path(tmp) / "g.jsonl"
            golden_path.write_text(json.dumps(ROW) + "\n", encoding="utf-8")
            state_path = Path(tmp) / "state.json"
            sig_a = dm.build_run_signature(
                "smoke", golden_path, global_run_id="run-a", reports_hash="hash-a")
            ss.StateStore(path=state_path, signature=sig_a).save()
            sig_b = dm.build_run_signature(
                "smoke", golden_path, global_run_id="run-a", reports_hash="hash-b")
            with self.assertRaises(ss.StateError):
                ss.StateStore.load_or_create(state_path, sig_b)


class Week5FilesUntouchedTests(unittest.TestCase):
    def test_week6_paths_never_point_inside_week5b(self) -> None:
        week5b_marker = "2026-11-11-week5-b"
        for path in (dm.RESULTS_DIR, dm.STATE_DIR, dm.CASES_DIR, dm.LEDGER_PATH,
                    dm.REPORT_INDEX_CACHE_PATH, dm.INDEX_COST_SUMMARY_PATH):
            self.assertNotIn(week5b_marker, str(path))
            self.assertIn("2026-11-14-week6-drift", str(path))


if __name__ == "__main__":
    unittest.main()
