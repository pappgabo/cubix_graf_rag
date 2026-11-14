import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import golden_set as gs
import measure
import state_store as ss

ROW = {
    "id": "X01", "type": "simple", "status": "frozen_w4", "question": "Q?",
    "expected_answer": "A.",
    "criteria": [{"id": "X01-c1", "text": "t1", "expected_content": ["a"], "required": True}],
    "evidence_groups": [{"id": "X01-e1", "criterion": "X01-c1", "any_of_chunk_ids": ["doc-a#0"]}],
    "gold_docs": ["doc-a"], "notes": "n", "golden_set_version": "test",
    "corpus": {"chunks_file": "x", "chunks_sha256": "abc", "chunk_count": 2},
}


def _question() -> gs.GoldenQuestion:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "g.jsonl"
        path.write_text(json.dumps(ROW) + "\n", encoding="utf-8")
        return gs.load_golden_set(path)[0]


def _complete_question_all_modes(question: gs.GoldenQuestion, case_dir: Path, store: ss.StateStore) -> None:
    """Drives every mode of one question through all four steps with a
    working (non-failing) fake ctx, so its case files and state end up
    exactly as a prior, fully successful run_cases() call would leave
    them -- used to set up a 'this case is already done' resume fixture."""
    ctx = _make_ctx(case_dir, gen_calls=[], judge_calls=[], langfuse_calls=[])
    for mode in measure.MODES:
        case = store.get_or_create(question.id, mode)
        while case.next_step() is not None:
            measure.process_case(question, mode, case, ctx)
    store.save()


@dataclass
class FakeResponse:
    content: str
    returned_model: str = "fake"
    usage_prompt_tokens: Any = 10
    usage_completion_tokens: Any = 5
    finish_reason: str = "stop"


class FakeBudget:
    """Minimal stand-in for cost_guard.SharedCostLedger: only the
    ``spent_usd`` attribute process_case actually reads. Fixtures below
    bump it by a known, fixed amount per fake call so tests can assert the
    exact resulting per-step cost delta."""

    def __init__(self) -> None:
        self.spent_usd = 0.0

    def add(self, amount: float) -> None:
        self.spent_usd = round(self.spent_usd + amount, 6)


GEN_COST = 0.001
CORRECTNESS_COST = 0.0002
FAITHFULNESS_COST = 0.0003


def _make_ctx(tmp_dir: Path, *, gen_calls: list, judge_calls: list,
             langfuse_calls: list, fail_at: str | None = None,
             budget: Any = None) -> measure.CaseContext:
    def naiv_fn(question):
        gen_calls.append(question.id)
        if budget is not None:
            budget.add(GEN_COST)
        if fail_at == "answer_saved":
            return {"error": "simulated generation failure"}
        return {
            "question_id": question.id, "mode": "naiv", "run_phase": "smoke",
            "answer": "Fake answer mentioning doc-a#0 content", "refused": False, "model_called": True,
            "actual_context": "ctx", "actual_chunk_ids": ["doc-a#0"], "chunk_ids_traceable": True,
            "is_proxy_retrieval": False, "error": None, "duration_seconds": 0.1,
        }

    def correctness_call_fn(system, user, max_tokens):
        judge_calls.append("correctness")
        if budget is not None:
            budget.add(CORRECTNESS_COST)
        if fail_at == "criteria_scored":
            raise RuntimeError("simulated judge failure")
        return FakeResponse(content=json.dumps({
            "criteria": [{"criterion_id": "X01-c1", "verdict": "met", "explanation": "ok"}],
            "refused": False, "rubric_conflicts": [], "reasoning": "ok",
        }))

    def faithfulness_call_fn(system, user, max_tokens):
        judge_calls.append("faithfulness")
        if budget is not None:
            budget.add(FAITHFULNESS_COST)
        if fail_at == "faithfulness_scored":
            raise RuntimeError("simulated faithfulness failure")
        return FakeResponse(content=json.dumps({
            "claims": [{"claim": "doc-a#0 content", "verdict": "supported"}], "reasoning": "ok",
        }))

    def langfuse_sync_fn(row):
        langfuse_calls.append(row["question_id"])
        if fail_at == "langfuse_synced":
            raise RuntimeError("simulated sync failure")

    return measure.CaseContext(
        run_phase="smoke", budget=budget, ledger=None,
        gen_fns={"naiv": naiv_fn, "lokalis": naiv_fn, "globalis": naiv_fn},
        correctness_call_fn_factory=lambda qid, mode, step: correctness_call_fn,
        faithfulness_call_fn_factory=lambda qid, mode, step: faithfulness_call_fn,
        langfuse_sync_fn=langfuse_sync_fn, case_store_dir=tmp_dir,
    )


class ProcessCaseTests(unittest.TestCase):
    def test_full_happy_path_completes_all_steps(self) -> None:
        q = _question()
        with tempfile.TemporaryDirectory() as tmp:
            gen_calls, judge_calls, langfuse_calls = [], [], []
            ctx = _make_ctx(Path(tmp), gen_calls=gen_calls, judge_calls=judge_calls, langfuse_calls=langfuse_calls)
            case = ss.CaseState(question_id=q.id, mode="naiv")
            while case.next_step() is not None:
                row = measure.process_case(q, "naiv", case, ctx)
            self.assertTrue(case.answer_saved and case.criteria_scored
                           and case.faithfulness_scored and case.langfuse_synced)
            self.assertEqual(row["correctness"]["label"], "helyes")
            self.assertIsNotNone(row["faithfulness"]["score"])

    def test_resume_only_runs_missing_steps(self) -> None:
        q = _question()
        with tempfile.TemporaryDirectory() as tmp:
            gen_calls, judge_calls, langfuse_calls = [], [], []
            ctx = _make_ctx(Path(tmp), gen_calls=gen_calls, judge_calls=judge_calls, langfuse_calls=langfuse_calls)
            case = ss.CaseState(question_id=q.id, mode="naiv", answer_saved=True, criteria_scored=True)
            # pre-seed the case row as if answer+criteria were already saved in a prior process
            row = measure._load_case_row(ctx, q.id, "naiv")
            row.update({"answer": "Fake answer mentioning doc-a#0 content",
                       "actual_context": "ctx", "actual_chunk_ids": ["doc-a#0"]})
            measure._save_case_row(ctx, q.id, "naiv", row)

            while case.next_step() is not None:
                measure.process_case(q, "naiv", case, ctx)

            self.assertEqual(gen_calls, [])  # generation was NOT re-run
            self.assertIn("faithfulness", judge_calls)
            self.assertNotIn("correctness", judge_calls)  # already scored, not re-run
            self.assertEqual(langfuse_calls, [q.id])

    def test_generation_error_halts_without_running_judges(self) -> None:
        q = _question()
        with tempfile.TemporaryDirectory() as tmp:
            gen_calls, judge_calls, langfuse_calls = [], [], []
            ctx = _make_ctx(Path(tmp), gen_calls=gen_calls, judge_calls=judge_calls,
                            langfuse_calls=langfuse_calls, fail_at="answer_saved")
            case = ss.CaseState(question_id=q.id, mode="naiv")
            with self.assertRaises(measure.MeasurementHalted):
                measure.process_case(q, "naiv", case, ctx)
            self.assertFalse(case.answer_saved)
            self.assertEqual(judge_calls, [])

    def test_judge_error_does_not_regenerate_answer(self) -> None:
        q = _question()
        with tempfile.TemporaryDirectory() as tmp:
            gen_calls, judge_calls, langfuse_calls = [], [], []
            ctx = _make_ctx(Path(tmp), gen_calls=gen_calls, judge_calls=judge_calls,
                            langfuse_calls=langfuse_calls, fail_at="criteria_scored")
            case = ss.CaseState(question_id=q.id, mode="naiv")
            measure.process_case(q, "naiv", case, ctx)  # answer_saved succeeds
            self.assertTrue(case.answer_saved)
            self.assertEqual(len(gen_calls), 1)
            with self.assertRaises(measure.MeasurementHalted):
                measure.process_case(q, "naiv", case, ctx)  # criteria_scored fails
            self.assertFalse(case.criteria_scored)
            self.assertEqual(len(gen_calls), 1)  # generation was not retried

    def test_run_cases_stops_whole_run_on_first_halt(self) -> None:
        q1, q2 = _question(), _question()
        q2 = gs.GoldenQuestion(**{**q1.__dict__, "id": "X02"})
        with tempfile.TemporaryDirectory() as tmp:
            gen_calls, judge_calls, langfuse_calls = [], [], []
            ctx = _make_ctx(Path(tmp), gen_calls=gen_calls, judge_calls=judge_calls,
                            langfuse_calls=langfuse_calls, fail_at="answer_saved")
            sig = ss.RunSignature(run_kind="smoke", config_sha256="c", golden_set_sha256="g")
            store = ss.StateStore(path=Path(tmp) / "state.json", signature=sig)
            with self.assertRaises(measure.MeasurementHalted):
                measure.run_cases([q1, q2], store, ctx)
            # only the first question's first mode should have been attempted
            self.assertEqual(gen_calls, ["X01"])

    def test_run_cases_resume_first_question_done_second_not(self) -> None:
        """Regression test for the reported crash: a case already fully
        complete from a prior run (case.next_step() is None from the
        start) must still produce a row in the resumed run_cases() call,
        read back from its saved case file -- not an UnboundLocalError,
        and not a re-run of its generation."""
        q1 = _question()
        q2 = gs.GoldenQuestion(**{**q1.__dict__, "id": "X02"})
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            sig = ss.RunSignature(run_kind="smoke", config_sha256="c", golden_set_sha256="g")
            store = ss.StateStore(path=case_dir / "state.json", signature=sig)
            _complete_question_all_modes(q1, case_dir, store)

            gen_calls, judge_calls, langfuse_calls = [], [], []
            ctx = _make_ctx(case_dir, gen_calls=gen_calls, judge_calls=judge_calls, langfuse_calls=langfuse_calls)
            rows = measure.run_cases([q1, q2], store, ctx)  # must not raise UnboundLocalError

            self.assertEqual(len(rows), 6)  # 2 questions x 3 modes
            q1_rows = [r for r in rows if r["question_id"] == "X01"]
            q2_rows = [r for r in rows if r["question_id"] == "X02"]
            self.assertEqual(len(q1_rows), 3)
            self.assertEqual(len(q2_rows), 3)
            for row in q1_rows:
                self.assertEqual(row["correctness"]["label"], "helyes")  # read from disk, not recomputed
                self.assertIsNotNone(row["faithfulness"]["score"])
            # q1 was already done: no generation call was repeated for it
            self.assertEqual(gen_calls, ["X02", "X02", "X02"])
            self.assertNotIn("X01", langfuse_calls)

    def test_save_never_trusts_a_mismatched_mode_from_the_generation_dict(self) -> None:
        """Found while building the resume fixtures above: a generation
        function's returned dict happened to hardcode the wrong "mode"
        value (reused across naiv/lokalis/globalis fakes). Confirms the
        actual case file for THIS mode still gets the generation content,
        and the other mode's file (if it already existed) is not clobbered."""
        q = _question()
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            sig = ss.RunSignature(run_kind="smoke", config_sha256="c", golden_set_sha256="g")
            store = ss.StateStore(path=case_dir / "state.json", signature=sig)

            def mislabeled_naiv_fn(question):
                return {
                    "question_id": "WRONG-ID", "mode": "naiv",  # always says "naiv", even when used as lokalis
                    "answer": "real lokalis answer", "refused": False, "model_called": True,
                    "actual_context": "ctx", "actual_chunk_ids": ["doc-a#0"], "chunk_ids_traceable": True,
                    "is_proxy_retrieval": False, "error": None, "duration_seconds": 0.1,
                }

            gen_calls, judge_calls, langfuse_calls = [], [], []
            ctx = _make_ctx(case_dir, gen_calls=gen_calls, judge_calls=judge_calls, langfuse_calls=langfuse_calls)
            ctx.gen_fns["lokalis"] = mislabeled_naiv_fn

            case = store.get_or_create(q.id, "lokalis")
            while case.next_step() is not None:
                measure.process_case(q, "lokalis", case, ctx)

            lokalis_file = case_dir / f"{q.id}-lokalis.json"
            naiv_file = case_dir / f"{q.id}-naiv.json"
            self.assertTrue(lokalis_file.exists())
            self.assertFalse(naiv_file.exists())  # never created despite the dict saying "mode": "naiv"
            saved = json.loads(lokalis_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["question_id"], q.id)  # not "WRONG-ID"
            self.assertEqual(saved["mode"], "lokalis")  # not "naiv"
            self.assertEqual(saved["answer"], "real lokalis answer")

    def test_run_cases_resume_both_questions_already_done(self) -> None:
        q1 = _question()
        q2 = gs.GoldenQuestion(**{**q1.__dict__, "id": "X02"})
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            sig = ss.RunSignature(run_kind="smoke", config_sha256="c", golden_set_sha256="g")
            store = ss.StateStore(path=case_dir / "state.json", signature=sig)
            _complete_question_all_modes(q1, case_dir, store)
            _complete_question_all_modes(q2, case_dir, store)

            gen_calls, judge_calls, langfuse_calls = [], [], []
            ctx = _make_ctx(case_dir, gen_calls=gen_calls, judge_calls=judge_calls, langfuse_calls=langfuse_calls)
            rows = measure.run_cases([q1, q2], store, ctx)  # must not raise UnboundLocalError

            self.assertEqual(len(rows), 6)
            self.assertEqual(gen_calls, [])  # nothing re-generated
            self.assertEqual(judge_calls, [])  # no judge re-run
            self.assertEqual(langfuse_calls, [])  # no re-sync
            for row in rows:
                self.assertEqual(row["correctness"]["label"], "helyes")


class SelectQuestionsTests(unittest.TestCase):
    def test_smoke_set_excludes_held_out(self) -> None:
        rows = []
        for qid in ("Q01", "Q07", "Q11", "Q14", "Q15"):
            row = dict(ROW)
            row["id"] = qid
            row["status"] = "held_out" if qid in ("Q14", "Q15") else "frozen_w4"
            rows.append(row)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            qs = gs.load_golden_set(path)
            smoke = measure.select_questions(qs, "smoke")
            ids = {q.id for q in smoke}
            self.assertEqual(ids, {"Q01", "Q07", "Q11"})
            self.assertNotIn("Q14", ids)
            self.assertNotIn("Q15", ids)

    def test_full_set_includes_all(self) -> None:
        rows = [dict(ROW, id=qid) for qid in ("Q01", "Q02")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            qs = gs.load_golden_set(path)
            full = measure.select_questions(qs, "full")
            self.assertEqual(len(full), 2)


if __name__ == "__main__":
    unittest.main()
