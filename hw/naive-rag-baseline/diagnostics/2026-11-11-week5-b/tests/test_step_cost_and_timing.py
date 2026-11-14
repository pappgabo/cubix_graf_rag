"""Regression tests for per-step cost/duration tracking
(measure.py's _spent_usd/_cost_delta/_recompute_total_cost and the
answer_saved/criteria_scored/faithfulness_scored branches of
process_case), resume preservation of already-saved step costs/times, and
judge log filename uniqueness (build_real_judge_call_fn_factory).

All fake/mock calls; nothing here reaches a real model, database, or
Langfuse endpoint. Judge-log tests write only into a temporary directory.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import measure
import state_store as ss
from tests.test_measure_orchestration import (
    CORRECTNESS_COST, FAITHFULNESS_COST, GEN_COST, FakeBudget, ROW, _make_ctx, _question,
)
import golden_set as gs


class PerStepCostTests(unittest.TestCase):
    def test_all_three_step_costs_recorded_and_summed(self) -> None:
        q = _question()
        with tempfile.TemporaryDirectory() as tmp:
            budget = FakeBudget()
            ctx = _make_ctx(Path(tmp), gen_calls=[], judge_calls=[], langfuse_calls=[], budget=budget)
            case = ss.CaseState(question_id=q.id, mode="naiv")
            row = None
            while case.next_step() is not None:
                row = measure.process_case(q, "naiv", case, ctx)

            self.assertAlmostEqual(row["cost_usd_generation"], GEN_COST)
            self.assertAlmostEqual(row["cost_usd_correctness_judge"], CORRECTNESS_COST)
            self.assertAlmostEqual(row["cost_usd_faithfulness_judge"], FAITHFULNESS_COST)
            self.assertAlmostEqual(row["cost_usd"], GEN_COST + CORRECTNESS_COST + FAITHFULNESS_COST)
            self.assertEqual(row["cost_source"], "ledger_delta")

    def test_cost_usd_stays_null_until_all_three_steps_known(self) -> None:
        q = _question()
        with tempfile.TemporaryDirectory() as tmp:
            budget = FakeBudget()
            ctx = _make_ctx(Path(tmp), gen_calls=[], judge_calls=[], langfuse_calls=[], budget=budget)
            case = ss.CaseState(question_id=q.id, mode="naiv")
            row = measure.process_case(q, "naiv", case, ctx)  # answer_saved only
            self.assertIsNotNone(row["cost_usd_generation"])
            self.assertNotIn("cost_usd_correctness_judge", row)
            self.assertIsNone(row.get("cost_usd"))  # not all three known yet -- never a partial sum

            row = measure.process_case(q, "naiv", case, ctx)  # criteria_scored
            self.assertIsNone(row.get("cost_usd"))  # still missing faithfulness

    def test_no_budget_wired_leaves_costs_null_not_zero(self) -> None:
        """Some fixtures (and older code paths) pass budget=None -- the
        per-step cost fields must be null, never silently 0.0."""
        q = _question()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _make_ctx(Path(tmp), gen_calls=[], judge_calls=[], langfuse_calls=[], budget=None)
            case = ss.CaseState(question_id=q.id, mode="naiv")
            row = measure.process_case(q, "naiv", case, ctx)
            self.assertIsNone(row["cost_usd_generation"])

    def test_generation_error_still_records_whatever_cost_was_incurred(self) -> None:
        q = _question()
        with tempfile.TemporaryDirectory() as tmp:
            budget = FakeBudget()
            ctx = _make_ctx(Path(tmp), gen_calls=[], judge_calls=[], langfuse_calls=[],
                            budget=budget, fail_at="answer_saved")
            case = ss.CaseState(question_id=q.id, mode="naiv")
            with self.assertRaises(measure.MeasurementHalted):
                measure.process_case(q, "naiv", case, ctx)
            saved = json.loads((Path(tmp) / f"{q.id}-naiv.json").read_text(encoding="utf-8"))
            # the fake gen_fn still "spent" GEN_COST before reporting an error
            self.assertAlmostEqual(saved["cost_usd_generation"], GEN_COST)


class PerStepDurationTests(unittest.TestCase):
    def test_generation_and_both_judges_have_separate_durations(self) -> None:
        q = _question()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _make_ctx(Path(tmp), gen_calls=[], judge_calls=[], langfuse_calls=[])
            case = ss.CaseState(question_id=q.id, mode="naiv")
            row = None
            while case.next_step() is not None:
                row = measure.process_case(q, "naiv", case, ctx)
            for field in ("duration_seconds_generation", "duration_seconds_correctness_judge",
                         "duration_seconds_faithfulness_judge"):
                self.assertIn(field, row)
                self.assertIsInstance(row[field], float)
                self.assertGreaterEqual(row[field], 0.0)


class ResumePreservesCostAndTimingTests(unittest.TestCase):
    def test_resume_keeps_earlier_step_costs_and_times_unchanged(self) -> None:
        q = _question()
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            budget = FakeBudget()
            ctx = _make_ctx(case_dir, gen_calls=[], judge_calls=[], langfuse_calls=[], budget=budget)
            case = ss.CaseState(question_id=q.id, mode="naiv")
            measure.process_case(q, "naiv", case, ctx)  # answer_saved: GEN_COST spent
            first_gen_cost = json.loads((case_dir / f"{q.id}-naiv.json").read_text())["cost_usd_generation"]
            first_gen_duration = json.loads(
                (case_dir / f"{q.id}-naiv.json").read_text())["duration_seconds_generation"]

            # simulate a resumed process: a NEW budget object (fresh spend
            # counter, as a new process would have), same case/row on disk
            budget2 = FakeBudget()
            ctx2 = _make_ctx(case_dir, gen_calls=[], judge_calls=[], langfuse_calls=[], budget=budget2)
            measure.process_case(q, "naiv", case, ctx2)  # criteria_scored only -- generation NOT re-run

            saved = json.loads((case_dir / f"{q.id}-naiv.json").read_text(encoding="utf-8"))
            self.assertAlmostEqual(saved["cost_usd_generation"], first_gen_cost)  # untouched
            self.assertAlmostEqual(saved["duration_seconds_generation"], first_gen_duration)  # untouched
            self.assertAlmostEqual(saved["cost_usd_correctness_judge"], CORRECTNESS_COST)
            self.assertAlmostEqual(budget2.spent_usd, CORRECTNESS_COST)  # generation not re-billed

    def test_old_rows_without_the_new_fields_report_null_not_zero(self) -> None:
        """A case fully completed before this fix has no cost_usd_* fields
        at all -- report.py (and any reader) must treat that as unknown,
        not as a known zero."""
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            old_row = {
                "question_id": "Q01", "mode": "naiv", "run_phase": "smoke",
                "answer": "old answer", "correctness": {"status": "scored", "label": "helyes"},
                "faithfulness": {"status": "scored", "score": 1.0},
            }
            (case_dir / "Q01-naiv.json").write_text(json.dumps(old_row), encoding="utf-8")
            loaded = measure._load_case_row(
                measure.CaseContext(run_phase="smoke", budget=None, ledger=None, gen_fns={},
                                    correctness_call_fn_factory=None, faithfulness_call_fn_factory=None,
                                    langfuse_sync_fn=None, case_store_dir=case_dir),
                "Q01", "naiv",
            )
            self.assertNotIn("cost_usd", loaded)
            self.assertNotIn("cost_usd_generation", loaded)


class _FakeLCResponse:
    def __init__(self) -> None:
        self.content = '{"ok": true}'
        self.response_metadata = {
            "model_name": "fake-model", "finish_reason": "stop",
            "token_usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
        self.usage_metadata = {}


class _FakeLCClient:
    def invoke(self, lc_messages):
        return _FakeLCResponse()


def _fake_client_factory(call_params):
    return _FakeLCClient()


class _PermissiveFakeBudget:
    """Only the two Budget methods build_real_judge_call_fn_factory's
    ``gated`` closure calls; always allows the call and reports zero cost
    (these tests are about log file naming, not cost math)."""

    def check_generative(self, input_tokens, max_output_tokens, label):
        return 0.0

    def record_generative(self, actual_usage_prompt, actual_usage_completion, upper_bound):
        return 0.0


class JudgeLogFilenameTests(unittest.TestCase):
    """Uses the REAL naive_rag.global_search_logging.make_logged_call_fn
    (via build_real_judge_call_fn_factory), with its documented
    ``client_factory`` injection point faked -- no real model/network call
    -- writing real log files into a temporary directory only."""

    def test_filename_contains_question_id_mode_and_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"
            factory = measure.build_real_judge_call_fn_factory(
                _PermissiveFakeBudget(), None, "correctness-smoke", log_dir,
                client_factory=_fake_client_factory,
            )
            call_fn = factory("Q01", "naiv", "criteria_scored")
            call_fn("system prompt", "user message", 200)

            written = list(log_dir.glob("*.json"))
            self.assertEqual(len(written), 1)
            name = written[0].name
            self.assertIn("Q01", name)
            self.assertIn("naiv", name)
            self.assertIn("criteria_scored", name)

    def test_two_attempts_for_the_same_case_step_never_collide_or_overwrite(self) -> None:
        """Simulates a halted-then-retried attempt: calling the factory
        twice for the identical (question_id, mode, step) must produce TWO
        distinct log files, and the first must still exist afterward."""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"
            factory = measure.build_real_judge_call_fn_factory(
                _PermissiveFakeBudget(), None, "correctness-smoke", log_dir,
                client_factory=_fake_client_factory,
            )
            first_call_fn = factory("Q01", "naiv", "criteria_scored")
            first_call_fn("system prompt", "user message v1", 200)
            first_files = set(log_dir.glob("*.json"))
            self.assertEqual(len(first_files), 1)

            second_call_fn = factory("Q01", "naiv", "criteria_scored")  # same identity, new attempt
            second_call_fn("system prompt", "user message v2", 200)
            second_files = set(log_dir.glob("*.json"))

            self.assertEqual(len(second_files), 2)  # a new file, not an overwrite
            self.assertTrue(first_files.issubset(second_files))  # the first attempt's log still exists

    def test_different_cases_never_share_a_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"
            factory = measure.build_real_judge_call_fn_factory(
                _PermissiveFakeBudget(), None, "faithfulness-smoke", log_dir,
                client_factory=_fake_client_factory,
            )
            factory("Q01", "naiv", "faithfulness_scored")("s", "u1", 200)
            factory("Q07", "lokalis", "faithfulness_scored")("s", "u2", 200)
            names = {p.name for p in log_dir.glob("*.json")}
            self.assertEqual(len(names), 2)
            self.assertTrue(any("Q01" in n and "naiv" in n for n in names))
            self.assertTrue(any("Q07" in n and "lokalis" in n for n in names))


if __name__ == "__main__":
    unittest.main()
